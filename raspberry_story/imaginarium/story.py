"""Generazione di una breve storia per bambini sul giocattolo riconosciuto.

Porting di ``toyclf/story.py`` (repo di sviluppo) adattato ai modelli piccoli
che girano su CPU sul Raspberry Pi 4 (default ``gemma3:4b``). Differenze
rispetto all'originale (che era tarato su ``qwen3:8b``):

- nessun soft-switch ``/no_think`` e nessuna gestione del campo ``think``
  dell'API Ollama: gemma3 non è un modello ibrido con blocco di
  ragionamento, quella logica non serve (la pulizia di un eventuale
  ``<think>`` in ``clean_output`` resta comunque, come rete di sicurezza a
  costo zero, ed è utile se si passa a un modello che invece pensa).
- parametri di default più bassi: su un Pi4 l'inferenza è limitata dalla
  banda di memoria, quindi il tempo scala quasi linearmente con i token
  generati e con la taglia del modello.
- il piano in due passate resta (separare "cosa succede" da "come scriverlo"
  è la leva principale sulla coerenza per un modello piccolo), ma è
  disattivabile: è anche la leva principale sulla *latenza*, perché ogni
  storia costa due generazioni complete invece di una.

Strumentazione
--------------
Ogni chiamata al modello produce una :class:`CallStats` (prompt inviato,
opzioni, tempo di parete, token e velocità riportati da Ollama, esito) e
tutte le chiamate di una generazione finiscono in :class:`StoryMetrics`,
allegata al :class:`StoryResult`. Serve a rispondere alla domanda che sta a
monte di ogni ottimizzazione — *quanto pesa il piano, quanto la prosa,
quanti retry scattano* — senza doverla dedurre dai log. Vedi
``bench_story.py``.

Il modulo non importa TensorFlow/TFLite: dipende solo da ``config``,
``urllib`` e dalla libreria standard.
"""

from __future__ import annotations

import json
import logging
import re
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

from .config import StoryConfig
from .exceptions import StoryGenerationError

logger = logging.getLogger(__name__)

# Le etichette del dataset sono in inglese (nomi delle cartelle): le classi
# principali hanno un traducente fisso, le sottoclassi (per lo più nomi
# propri, es. "super_mario") passano così come sono.
_MAIN_CLASS_IT = {
    "action_figure": "action figure",
    "animal": "animale di peluche",
    "construction_set": "gioco di costruzioni",
    "doll_and_dollhouse": "bambola",
    "electronic_and_robot": "robot giocattolo",
    "physical_activity": "gioco da fare all'aperto",
    "puzzle_and_game": "gioco da tavolo",
    "role_play_and_tools": "gioco di imitazione",
    "vehicle": "veicolo giocattolo",
}

GENERIC_SUBJECT = "giocattolo"

SYSTEM_PROMPT = (
    "Sei un narratore per bambini dai 4 agli 8 anni. Scrivi SOLO in italiano "
    "corretto e naturale, mai in inglese. Usa frasi brevi, lessico semplice e "
    "un tempo verbale coerente dall'inizio alla fine. Non usare elenchi, "
    "titoli, emoji, note o commenti sul tuo lavoro: produci esclusivamente il "
    "testo della storia."
)

PLAN_SYSTEM_PROMPT = (
    "Sei un autore di storie per bambini. Rispondi SOLO con un oggetto JSON "
    "valido, senza testo prima o dopo, senza blocchi di codice. Tutti i valori "
    "sono in italiano."
)

_PLAN_FIELDS = ("nome", "genere", "luogo", "problema", "svolta", "finale", "morale")

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
_PREAMBLE_LINE = re.compile(
    r"^\s*(?:#{1,6}\s.*|\*\*.*\*\*|(?:ecco|certo|volentieri|titolo|storia)\b[^.!?]{0,80}:)\s*$",
    re.IGNORECASE,
)


# ── Statistiche ───────────────────────────────────────────────────────────


def _ns_to_s(value: Any) -> float | None:
    """Durata Ollama (nanosecondi) -> secondi, tollerante ai campi assenti."""
    if not isinstance(value, (int, float)):
        return None
    return float(value) / 1e9


@dataclass
class CallStats:
    """Che cosa è stato chiesto al modello, e quanto è costato.

    Non è congelata di proposito: ``outcome`` viene deciso dal chiamante
    *dopo* la chiamata, quando il testo è stato validato.
    """

    label: str  # "piano #1", "prosa #1", "warmup", ...
    model: str
    prompt: str
    system: str
    options: dict[str, Any]
    response: str = ""
    wall_s: float = 0.0  # tempo di parete misurato qui
    total_duration_s: float | None = None  # riportato da Ollama
    load_duration_s: float | None = None  # caricamento del modello in RAM
    prompt_eval_count: int | None = None  # token del prompt
    prompt_eval_duration_s: float | None = None
    eval_count: int | None = None  # token generati
    eval_duration_s: float | None = None
    done_reason: str | None = None  # "stop" | "length" | ...
    outcome: str = "ok"  # "ok" | "scartato: ..." | ...

    @property
    def eval_tokens_per_s(self) -> float | None:
        """Velocità di generazione (token/s), la metrica che conta su CPU."""
        if not self.eval_count or not self.eval_duration_s:
            return None
        return self.eval_count / self.eval_duration_s

    @property
    def prompt_tokens_per_s(self) -> float | None:
        if not self.prompt_eval_count or not self.prompt_eval_duration_s:
            return None
        return self.prompt_eval_count / self.prompt_eval_duration_s

    @property
    def hit_token_limit(self) -> bool:
        """Vero se la generazione si è fermata per esaurimento di num_predict."""
        return self.done_reason == "length"

    def to_dict(self, *, include_prompt: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "label": self.label,
            "model": self.model,
            "wall_s": round(self.wall_s, 3),
            "load_s": round(self.load_duration_s, 3) if self.load_duration_s else None,
            "prompt_tokens": self.prompt_eval_count,
            "eval_tokens": self.eval_count,
            "eval_tokens_per_s": (
                round(self.eval_tokens_per_s, 2) if self.eval_tokens_per_s else None
            ),
            "done_reason": self.done_reason,
            "outcome": self.outcome,
        }
        if include_prompt:
            data["system"] = self.system
            data["prompt"] = self.prompt
            data["options"] = self.options
            data["response"] = self.response
        return data


@dataclass
class StoryMetrics:
    """Tutte le chiamate al modello fatte per produrre una storia."""

    calls: list[CallStats] = field(default_factory=list)
    wall_s: float = 0.0  # tempo totale di generate_story()

    def add(self, call: CallStats) -> CallStats:
        self.calls.append(call)
        return call

    def by_phase(self, phase: str) -> list[CallStats]:
        """Chiamate di una fase ("piano" o "prosa")."""
        return [c for c in self.calls if c.label.startswith(phase)]

    def phase_wall_s(self, phase: str) -> float:
        return sum(c.wall_s for c in self.by_phase(phase))

    @property
    def plan_wall_s(self) -> float:
        return self.phase_wall_s("piano")

    @property
    def prose_wall_s(self) -> float:
        return self.phase_wall_s("prosa")

    @property
    def total_eval_tokens(self) -> int:
        return sum(c.eval_count or 0 for c in self.calls)

    @property
    def total_prompt_tokens(self) -> int:
        return sum(c.prompt_eval_count or 0 for c in self.calls)

    @property
    def eval_tokens_per_s(self) -> float | None:
        """Velocità media pesata sulle sole fasi di generazione."""
        total_s = sum(c.eval_duration_s or 0.0 for c in self.calls)
        if not total_s or not self.total_eval_tokens:
            return None
        return self.total_eval_tokens / total_s

    @property
    def discarded(self) -> int:
        return sum(1 for c in self.calls if c.outcome.startswith("scartato"))

    def summary(self) -> dict[str, Any]:
        return {
            "wall_s": round(self.wall_s, 2),
            "plan_wall_s": round(self.plan_wall_s, 2),
            "prose_wall_s": round(self.prose_wall_s, 2),
            "calls": len(self.calls),
            "discarded": self.discarded,
            "prompt_tokens": self.total_prompt_tokens,
            "eval_tokens": self.total_eval_tokens,
            "eval_tokens_per_s": (
                round(self.eval_tokens_per_s, 2) if self.eval_tokens_per_s else None
            ),
        }


# Firma del trasporto verso il modello: iniettabile nei test.
OllamaCaller = Callable[..., CallStats]


# ── Scelta del soggetto ───────────────────────────────────────────────────


def humanize_label(label: str) -> str:
    """Etichetta del dataset -> forma leggibile in italiano."""
    if label in _MAIN_CLASS_IT:
        return _MAIN_CLASS_IT[label]
    return label.replace("_", " ")


def main_class_subjects() -> list[str]:
    """I 9 soggetti corrispondenti alle macro-classi del classificatore.

    Serve al banco di prova per coprire l'intero spazio dei soggetti reali
    invece di misurare sempre sullo stesso esempio.
    """
    return list(_MAIN_CLASS_IT.values())


def choose_subject(
    main_class: str,
    sub_class: str | None,
    main_confidence: float,
    sub_confidence: float | None,
    config: StoryConfig,
) -> str:
    """Sceglie di *cosa* parlare, dosando la specificità con la confidenza.

    Una sottoclasse predetta male produce una storia perfettamente coerente
    sull'oggetto sbagliato: quando il classificatore è incerto conviene
    scendere alla classe principale, e se anche quella è incerta parlare di
    un giocattolo generico.
    """
    if main_confidence < config.min_main_confidence:
        logger.info(
            "Confidenza principale bassa (%.2f): storia su un soggetto generico", main_confidence
        )
        return GENERIC_SUBJECT
    if sub_class and (sub_confidence is None or sub_confidence >= config.min_sub_confidence):
        return humanize_label(sub_class)
    logger.info("Sottoclasse incerta: la storia usa la classe principale '%s'", main_class)
    return humanize_label(main_class)


# ── Piano narrativo ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class StoryPlan:
    """Scheletro della storia, prodotto dalla prima passata."""

    nome: str
    genere: str
    luogo: str
    problema: str
    svolta: str
    finale: str
    morale: str

    @classmethod
    def from_response(cls, raw: str) -> "StoryPlan":
        """Costruisce il piano dal JSON restituito dal modello.

        Raises:
            StoryGenerationError: risposta non parsabile o campi mancanti.
        """
        data = _extract_json_object(raw)
        missing = [f for f in _PLAN_FIELDS if not str(data.get(f, "")).strip()]
        if missing:
            raise StoryGenerationError(f"Piano incompleto, campi mancanti: {', '.join(missing)}")
        values = {f: " ".join(str(data[f]).split()) for f in _PLAN_FIELDS}
        return cls(**values)

    def as_briefing(self, subject: str = GENERIC_SUBJECT) -> str:
        """Il piano nella forma compatta che viene rimessa nel prompt.

        ``subject`` viene ripetuto qui perché il modello, avendo davanti un
        nome proprio, tende a trasformare il protagonista in un bambino e a
        relegare il giocattolo a comparsa.
        """
        return (
            f"- Protagonista: {self.nome}, genere {self.genere}. È il giocattolo stesso "
            f"({subject}) che parla e agisce, non un bambino che ci gioca.\n"
            f"- Luogo unico: {self.luogo}\n"
            f"- Problema: {self.problema}\n"
            f"- Svolta: {self.svolta}\n"
            f"- Finale: {self.finale}\n"
            f"- Messaggio da trasmettere senza mai enunciarlo: {self.morale}"
        )

    def to_dict(self) -> dict[str, str]:
        return {f: getattr(self, f) for f in _PLAN_FIELDS}


# Piano fittizio, usato solo da ``bench_story.py --dry-run`` per mostrare che
# forma ha il prompt della seconda passata senza chiamare il modello.
EXAMPLE_PLAN = StoryPlan(
    nome="Nino",
    genere="maschile",
    luogo="lo scaffale più alto della cameretta",
    problema="non riesce a raggiungere gli amici rimasti in fondo alla scatola",
    svolta="dopo un primo salto andato male, chiede aiuto e costruisce una rampa",
    finale="tutti tornano insieme sullo scaffale e ridono dell'impresa",
    morale="chiedere aiuto non è una sconfitta",
)


def _extract_json_object(raw: str) -> dict[str, Any]:
    """Estrae il primo oggetto JSON dal testo (tollera testo attorno)."""
    text = clean_output(raw)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise StoryGenerationError("Il modello non ha restituito un oggetto JSON")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise StoryGenerationError(f"JSON del piano non valido: {exc}") from exc
    if not isinstance(data, dict):
        raise StoryGenerationError("Il piano deve essere un oggetto JSON")
    return data


# ── Prompt ────────────────────────────────────────────────────────────────


def build_plan_prompt(subject: str) -> str:
    """Prompt della prima passata: solo lo scheletro, niente prosa."""
    return (
        f"Progetta una storia per bambini con protagonista questo giocattolo: {subject}.\n\n"
        "Rispondi con un oggetto JSON con esattamente queste chiavi:\n"
        '  "nome": nome proprio del giocattolo protagonista (una o due parole)\n'
        '  "genere": "maschile" oppure "femminile"\n'
        '  "luogo": un unico luogo concreto dove si svolge tutto (poche parole)\n'
        '  "problema": il problema che il protagonista deve affrontare (una frase)\n'
        '  "svolta": cosa fa per risolverlo dopo un primo tentativo fallito (una frase)\n'
        '  "finale": come si chiude la vicenda (una frase)\n'
        '  "morale": il valore educativo, scegline uno adatto al problema (poche parole)\n\n'
        f"Il protagonista è il giocattolo stesso ({subject}), che è vivo e agisce: "
        "non un bambino che ci gioca.\n"
        "Il problema deve essere adatto a bambini piccoli: niente violenza, "
        "malattia, morte o paure forti. Rispondi SOLO con il JSON, nient'altro."
    )


def build_story_prompt(subject: str, plan: StoryPlan | None, config: StoryConfig) -> str:
    """Prompt della seconda passata (o passata unica se ``plan`` è ``None``)."""
    target = config.word_target
    header = f"Scrivi una storia per bambini con protagonista questo giocattolo: {subject}.\n\n"
    if plan is not None:
        header += "Segui questo piano, senza aggiungere altri elementi:\n"
        header += plan.as_briefing(subject) + "\n\n"
        name_rule = f"- Chiama il protagonista sempre e solo {plan.nome}.\n"
    else:
        name_rule = "- Dai un nome proprio al protagonista e usa sempre quello.\n"
        # In passata unica il modello non ha uno scheletro davanti: gli si
        # chiede di fissarlo mentalmente prima di scrivere, altrimenti la
        # storia divaga. È il compromesso di coerenza che si paga
        # disattivando two_pass, mitigato al costo di poche decine di token.
        header += (
            "Prima di scrivere fissa mentalmente: un luogo, un problema adatto a "
            "bambini piccoli, una svolta dopo un primo tentativo fallito, un finale "
            "sereno. Poi scrivi soltanto la storia, senza elencare questi punti.\n\n"
        )
    return header + (
        "Regole da rispettare:\n"
        f"- Lunghezza: circa {target} parole.\n"
        f"- Il protagonista è il giocattolo ({subject}), vivo e al centro della storia.\n"
        "- Racconta in terza persona, mai in prima persona.\n"
        + name_rule
        + "- UN solo protagonista, al massimo un personaggio secondario.\n"
        "- Un solo luogo, non cambiarlo a metà storia.\n"
        "- Struttura semplice: presentazione, problema, soluzione, chiusura.\n"
        "- Chiudi con una frase che faccia capire il messaggio senza dichiararlo.\n"
        "- Niente titolo, niente introduzione, niente commenti finali.\n\n"
        "Storia:"
    )


# ── Pulizia dell'output ───────────────────────────────────────────────────


def clean_output(text: str) -> str:
    """Rimuove eventuale reasoning, preamboli e decorazioni markdown.

    Gemma3 non emette un blocco ``<think>``, ma la pulizia resta come rete
    di sicurezza economica (e utile se in futuro si cambia modello) per
    quando il modello premette comunque "Ecco la storia:" o simili.
    """
    text = _THINK_BLOCK.sub("", text)
    if "</think>" in text:
        text = text.split("</think>")[-1]
    text = text.replace("<think>", "").strip()

    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()

    lines = text.split("\n")
    while lines and (not lines[0].strip() or _PREAMBLE_LINE.match(lines[0])):
        lines.pop(0)
    text = "\n".join(lines).strip()

    if len(text) > 1 and text[0] in "\"«“" and text[-1] in "\"»”":
        text = text[1:-1].strip()
    return text


def word_count(text: str) -> int:
    """Numero di parole del testo."""
    return len(text.split())


def looks_truncated(text: str) -> bool:
    """Vero se il testo si interrompe a metà frase (sintomo di num_predict basso)."""
    stripped = text.rstrip().rstrip("\"»”'")
    return bool(stripped) and stripped[-1] not in ".!?…"


# ── Trasporto verso Ollama ────────────────────────────────────────────────


def build_options(
    config: StoryConfig,
    *,
    num_predict: int | None = None,
    temperature: float | None = None,
) -> dict[str, Any]:
    """Il blocco ``options`` inviato a Ollama, senza chiavi vuote.

    Estratto da ``call_ollama`` perché il banco di prova lo mostra anche in
    ``--dry-run``, quando nessuna chiamata viene fatta davvero.
    """
    options: dict[str, Any] = {
        "num_predict": num_predict if num_predict is not None else config.num_predict,
        "num_ctx": config.num_ctx,
        "temperature": temperature if temperature is not None else config.temperature,
        "top_p": config.top_p,
        "top_k": config.top_k,
        "repeat_penalty": config.repeat_penalty,
    }
    if config.seed is not None:
        options["seed"] = config.seed
    if config.num_thread is not None:
        options["num_thread"] = config.num_thread
    if config.num_batch is not None:
        options["num_batch"] = config.num_batch
    if config.stop:
        options["stop"] = list(config.stop)
    return options


def call_ollama(
    prompt: str,
    config: StoryConfig,
    *,
    system: str = SYSTEM_PROMPT,
    num_predict: int | None = None,
    temperature: float | None = None,
    json_format: bool = False,
    label: str = "generazione",
) -> CallStats:
    """Chiama l'endpoint generate di Ollama e restituisce testo + statistiche.

    Raises:
        StoryGenerationError: server irraggiungibile, timeout o risposta
            non interpretabile.
    """
    options = build_options(config, num_predict=num_predict, temperature=temperature)

    body: dict[str, Any] = {
        "model": config.ollama_model,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": options,
    }
    if config.keep_alive:
        body["keep_alive"] = config.keep_alive
    if json_format:
        body["format"] = "json"

    stats = CallStats(
        label=label,
        model=config.ollama_model,
        prompt=prompt,
        system=system,
        options=options,
    )

    request = urllib.request.Request(
        config.ollama_url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    logger.debug(
        "Richiesta a Ollama (%s, modello %s, fase '%s', num_predict %s)",
        config.ollama_url,
        config.ollama_model,
        label,
        options["num_predict"],
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=config.timeout_s) as response:
            result = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:200]
        raise StoryGenerationError(
            f"Ollama ha risposto {exc.code}: {detail}. "
            f"Il modello '{config.ollama_model}' è stato scaricato "
            f"(`ollama pull {config.ollama_model}`)?"
        ) from exc
    except urllib.error.URLError as exc:
        raise StoryGenerationError(
            f"Ollama non raggiungibile su {config.ollama_url} ({exc.reason}). "
            "Il server è attivo (`ollama serve`, o già avviato come servizio)?"
        ) from exc
    except TimeoutError as exc:
        raise StoryGenerationError(
            f"Timeout dopo {config.timeout_s}s: su CPU (Raspberry Pi 4) un modello da "
            "qualche miliardo di parametri può essere lento — aumenta story.timeout_s, "
            "riduci story.num_predict/num_ctx, disattiva story.two_pass, oppure passa a "
            "un modello più piccolo (vedi `python bench_story.py --list-presets`)."
        ) from exc
    except json.JSONDecodeError as exc:
        raise StoryGenerationError(f"Risposta di Ollama non è JSON: {exc}") from exc
    finally:
        stats.wall_s = time.perf_counter() - started

    stats.response = str(result.get("response", "")).strip()
    stats.total_duration_s = _ns_to_s(result.get("total_duration"))
    stats.load_duration_s = _ns_to_s(result.get("load_duration"))
    stats.prompt_eval_count = result.get("prompt_eval_count")
    stats.prompt_eval_duration_s = _ns_to_s(result.get("prompt_eval_duration"))
    stats.eval_count = result.get("eval_count")
    stats.eval_duration_s = _ns_to_s(result.get("eval_duration"))
    stats.done_reason = result.get("done_reason")

    logger.debug(
        "Fase '%s': %.1fs, %s token generati (%s tok/s), stop=%s",
        label,
        stats.wall_s,
        stats.eval_count,
        f"{stats.eval_tokens_per_s:.1f}" if stats.eval_tokens_per_s else "n/d",
        stats.done_reason,
    )
    return stats


def warmup(config: StoryConfig, caller: OllamaCaller = call_ollama) -> CallStats:
    """Genera un token a vuoto per forzare il caricamento del modello in RAM.

    Su un Pi4 il primo ``load_duration`` di un modello da qualche GB può
    valere svariati secondi: misurare una configurazione senza scaldarla
    prima significa attribuire alla generazione un costo che è di I/O.
    """
    return caller(
        "Ciao",
        config,
        system="Rispondi con una sola parola.",
        num_predict=1,
        label="warmup",
    )


# ── API principale ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StoryResult:
    """Testo generato più il piano che lo ha guidato (utile per il debug)."""

    text: str
    subject: str
    plan: StoryPlan | None = None
    attempts: int = 1
    metrics: StoryMetrics = field(default_factory=StoryMetrics)
    # Il prompt effettivamente usato per la prosa: è ciò che si vuole
    # rileggere quando una configurazione produce un risultato strano.
    prompt: str = ""

    def __str__(self) -> str:
        return self.text

    @property
    def words(self) -> int:
        return word_count(self.text)


def generate_plan(
    subject: str,
    config: StoryConfig,
    caller: OllamaCaller = call_ollama,
    *,
    metrics: StoryMetrics | None = None,
    label: str = "piano",
) -> StoryPlan:
    """Prima passata: lo scheletro narrativo in JSON.

    Raises:
        StoryGenerationError: il modello non ha prodotto un piano valido.
    """
    stats = caller(
        build_plan_prompt(subject),
        config,
        system=PLAN_SYSTEM_PROMPT,
        num_predict=config.plan_num_predict,
        temperature=config.plan_temperature,
        json_format=True,
        label=label,
    )
    if metrics is not None:
        metrics.add(stats)
    try:
        plan = StoryPlan.from_response(stats.response)
    except StoryGenerationError as exc:
        stats.outcome = f"scartato: {exc}"
        raise
    logger.debug("Piano generato: %s", plan)
    return plan


def _plan_with_retries(
    subject: str,
    config: StoryConfig,
    caller: OllamaCaller,
    metrics: StoryMetrics,
) -> StoryPlan | None:
    """Il piano, ritentato ``plan_max_retries`` volte; ``None`` se non arriva.

    Un piano che non parsa non è fatale: la generazione prosegue in passata
    unica, perché una storia meno solida è preferibile a nessuna storia. Ma
    ogni ritentativo costa una generazione intera, quindi il default è zero
    ritentativi: se il JSON fallisce spesso conviene abbassare
    ``plan_temperature`` prima di alzare ``plan_max_retries``.
    """
    for attempt in range(1, config.plan_max_retries + 2):
        try:
            return generate_plan(
                subject, config, caller, metrics=metrics, label=f"piano #{attempt}"
            )
        except StoryGenerationError as exc:
            logger.warning("Piano non utilizzabile al tentativo %d (%s)", attempt, exc)
    logger.warning("Nessun piano valido: passo alla generazione diretta")
    return None


def generate_story(
    subject: str,
    config: StoryConfig,
    *,
    caller: OllamaCaller = call_ollama,
) -> StoryResult:
    """Storia breve sul soggetto indicato (già in forma leggibile).

    Con ``config.two_pass`` genera prima il piano; se il piano fallisce la
    generazione prosegue comunque in passata unica.

    Il risultato porta con sé :class:`StoryMetrics`, cioè quanto è costata
    ogni fase: è il dato che serve per decidere quale leva di configurazione
    tirare (vedi ``bench_story.py``).

    Raises:
        StoryGenerationError: il modello non è raggiungibile o non ha
            prodotto testo utilizzabile.
    """
    metrics = StoryMetrics()
    started = time.perf_counter()
    try:
        plan: StoryPlan | None = None
        if config.two_pass:
            plan = _plan_with_retries(subject, config, caller, metrics)

        prompt = build_story_prompt(subject, plan, config)
        text = ""
        for attempt in range(1, config.max_retries + 2):
            # I tentativi successivi al primo alzano il budget di token: la
            # causa più comune di un testo scartato è il troncamento. Il
            # fattore di crescita è configurabile perché su CPU raddoppiare
            # il budget significa raddoppiare l'attesa.
            budget = max(1, round(config.num_predict * config.retry_growth ** (attempt - 1)))
            stats = metrics.add(
                caller(prompt, config, num_predict=budget, label=f"prosa #{attempt}")
            )
            text = clean_output(stats.response)
            if not text:
                stats.outcome = "scartato: risposta vuota"
                logger.warning("Tentativo %d: risposta vuota", attempt)
                continue

            words = word_count(text)
            truncated = looks_truncated(text)
            too_short = words < config.min_words
            rejected = too_short or (truncated and not config.accept_truncated)
            if not rejected:
                if truncated:
                    stats.outcome = "ok (troncata, accettata)"
                return StoryResult(
                    text=text,
                    subject=subject,
                    plan=plan,
                    attempts=attempt,
                    metrics=metrics,
                    prompt=prompt,
                )

            reason = f"troppo corta ({words} parole, minimo {config.min_words})"
            if not too_short:
                reason = f"troncata a metà frase ({words} parole)"
            stats.outcome = f"scartato: {reason}"
            logger.warning(
                "Tentativo %d scartato (%d parole, troncata=%s)", attempt, words, truncated
            )

        if not text:
            raise StoryGenerationError(
                f"Il modello '{config.ollama_model}' non ha prodotto testo utilizzabile"
            )
        logger.warning("Restituisco l'ultimo tentativo nonostante i controlli di qualità")
        return StoryResult(
            text=text,
            subject=subject,
            plan=plan,
            attempts=config.max_retries + 1,
            metrics=metrics,
            prompt=prompt,
        )
    finally:
        metrics.wall_s = time.perf_counter() - started


# ── Aggregazione su più esecuzioni ────────────────────────────────────────


def aggregate(values: list[float]) -> dict[str, float]:
    """Riassunto di una serie di misure (usato dal banco di prova)."""
    if not values:
        return {}
    return {
        "n": float(len(values)),
        "media": statistics.fmean(values),
        "mediana": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "dev_std": statistics.pstdev(values) if len(values) > 1 else 0.0,
    }
