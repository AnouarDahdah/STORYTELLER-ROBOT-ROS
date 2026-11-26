# 6. I 3 comandi

## 6.1 Cosa fa ciascuno

**Comando 1 — racconta in tutte le lingue.**
Scatta una foto → classifica il giocattolo (classe principale + sottoclasse,
`imaginarium/inference/hierarchical.py`) → sceglie il soggetto della storia
in base alla confidenza (`imaginarium/subjects.py`): se il sottoclassificatore
è sicuro almeno al **50%**, storia sulla sottoclasse (se il pool la copre,
altrimenti sulla classe principale); se anche la classe principale è incerta
sotto il **55%**, storia su un soggetto completamente generico. Pesca **una**
storia dal pool (`imaginarium/story_cache.py`) e la racconta nelle **3
lingue configurate**, nell'ordine `languages: [it, en, sl]` di `config.yaml`
— stessa storia, stesso protagonista (il nome non cambia da una lingua
all'altra, vedi sotto), letta tre volte con la voce Piper di ciascuna
lingua.

```bash
python run_button.py 1
python run_button.py 1 --image foto_di_test.jpg --no-play --stats --json
```

**Comando 2 — racconta in una lingua sola.**
Stessa logica di scatto/classificazione/scelta del soggetto del comando 1,
ma sintetizza e riproduce **una sola lingua**, indicata esplicitamente.
Salva anche **quale** storia ha raccontato (soggetto, indice nel pool,
lingua) in `runtime/last_story.json` — è il collegamento verso il comando 3.

```bash
python run_button.py 2 --lang it
python run_button.py 2 --lang en
python run_button.py 2 --lang sl
```

**Comando 3 — "traduce" la storia del comando 2.**
Non scatta né classifica nulla: legge `runtime/last_story.json` (l'ultimo
comando 2 eseguito) e recupera dal pool, **allo stesso indice**, la
versione della stessa storia nelle **altre due lingue** — quella che
`Traduzione storie/translate_stories.py` ha già tradotto offline, non una
traduzione fatta sul momento. La racconta in sequenza in quelle due lingue.

```bash
python run_button.py 3
```

Se il comando 3 viene eseguito senza che il comando 2 sia mai girato prima
(nessun `runtime/last_story.json`), fallisce con un errore esplicito
("Esegui prima il comando 2") invece di indovinare.

## 6.2 Perché nessuno dei tre chiama un modello di linguaggio

La versione precedente di questa pipeline generava la storia con un LLM
locale (Ollama) al momento dello scatto: su un Pi 4, minuti di attesa e
qualche GB di RAM occupata dal modello. I 3 comandi qui descritti **pescano
sempre da un pool pre-generato** (`runtime/stories_it.json` / `_en.json` /
`_sl.json`, vedi [`05_modelli_e_storie.md`](05_modelli_e_storie.md)): la
fase "scelta della storia" è una lettura da un file JSON già in RAM,
millisecondi invece di minuti. Il percorso storico con Ollama
(`run_pipeline.py`, `imaginarium/pipeline.py`/`story.py`) resta nel repo per
chi vuole generare **nuove** storie o sperimentare in fase di sviluppo, ma
**non è necessario installare Ollama sul Raspberry Pi**: `config.yaml` ha
`cache.fallback_to_model: false` di default, quindi i 3 comandi non lo
cercano nemmeno.

## 6.3 Il nome del protagonista resta coerente fra le lingue

Le storie del pool hanno spesso un protagonista con un nome proprio (es.
"Nino"). La traduzione (`translate_stories.py`) non tocca quel nome
apposta — è la stessa cosa in ogni lingua. `story_cache.py` sfrutta questo
per personalizzare il protagonista (cambiargli nome a ogni estrazione, per
non sembrare sempre la stessa identica storia) **una sola volta**, e applica
lo stesso nome nuovo a tutte le lingue pescate insieme: il comando 1 non
farà mai dire "Nino" in italiano e "Bea" in inglese per lo stesso
personaggio. Disattivabile con `cache.personalize_name: false` in
`config.yaml`.

## 6.4 Oggi tastiera, domani pulsanti fisici

`run_button.py` è deliberatamente un guscio sottile: ogni comando è **una
chiamata a una funzione pura** di `imaginarium/commands.py`
(`run_command_1(config)`, `run_command_2(config, lang)`,
`run_command_3(config)`), che non sa nulla di come è stata invocata. Quando
i pulsanti fisici saranno collegati (GPIO), ogni callback del pulsante
chiamerà direttamente quella funzione — nessuna delle tre sa se chi le ha
chiamate è una riga di comando o un interrupt hardware. Uno scheletro
indicativo (da adattare quando i pulsanti saranno scelti/cablati):

```python
# esempio indicativo, non incluso in questo repo: dipende dalla libreria
# GPIO scelta (RPi.GPIO, gpiozero, lgpio, ...) e dal cablaggio dei pulsanti.
from imaginarium.cli import bootstrap
from imaginarium.commands import run_command_1, run_command_2, run_command_3

config = bootstrap(None)

def on_button_1_pressed():
    run_command_1(config)

def on_button_2_pressed():
    run_command_2(config, lang="it")  # o la lingua scelta con un secondo controllo

def on_button_3_pressed():
    run_command_3(config)
```

Nessuna logica dei comandi va duplicata o riscritta per i pulsanti: solo il
trigger cambia.

## 6.5 Copertura del pool e cosa succede se manca una storia

`imaginarium/subjects.py` garantisce che **ogni** classe principale abbia un
bucket di storie valido (vedi [`05_modelli_e_storie.md`](05_modelli_e_storie.md),
sezione 5.4, per i 5 casi che oggi usano un bucket generico invece di uno
dedicato): un comando non dovrebbe mai fallire per "nessuna storia trovata"
con il pool attuale. Se succede comunque (es. un pool copiato a metà, o un
file corrotto), il comando termina con un `CommandError` esplicito che nomina
il soggetto mancante — mai un silenzio o un fallback a caso.

Prossimo passo: [`07_monitoraggio_risorse.md`](07_monitoraggio_risorse.md)
per osservare CPU/RAM mentre provi i comandi.
