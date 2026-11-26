"""Costruisce ``models/subject_map.json``: dalle etichette grezze del
classificatore (cartelle del dataset, in ``models/hierarchy.json``) alle
chiavi del pool di storie pre-generate (``lettura storie/stories2.json``).

Perché serve
------------
Il classificatore riconosce 15 classi principali e 294 sottoclassi (nomi di
cartella: ``tartarughe_ninja``, ``supermario``, ``spiederman`` con un refuso,
...). Il pool di storie è invece indicizzato su chiavi scelte a mano quando le
storie sono state generate (``"ninja turtle"``, ``"super mario"``,
``"spiderman"``, ...), che non sono le stesse stringhe e in parte sono in
un'altra lingua. Senza una mappa esplicita, "ho riconosciuto una tartaruga
ninja" e "ho una storia su 'ninja turtle'" restano due mondi separati.

Come funziona
-------------
Per ogni etichetta grezza, in ordine di fiducia:

1. **override esplicito** — la mappa ``SUBCLASS_OVERRIDES`` sotto, curata a
   mano confrontando le due liste (traduzioni, refusi nel pool da rispettare
   così come sono, bucket generici tipo tutte le palle -> ``"ball"``).
2. **corrispondenza esatta dopo normalizzazione** — stessa parola, solo
   ``_`` al posto di spazio (es. ``elastico_per_capelli`` ->
   ``"elastico per capelli"``): non richiede override, si mantiene da sola
   se in futuro si aggiungono sottoclassi con lo stesso pattern.
3. **corrispondenza sfocata** (``difflib``, soglia alta) — rete di sicurezza
   per refusi minori non ancora visti; finisce comunque nel report come
   "da verificare".
4. **nessuna corrispondenza** — è la maggioranza (le sottoclassi coperte da
   una storia specifica sono ~174 su 294): a runtime ``subjects.py`` risale
   alla storia della classe principale.

La classe principale (15, tassonomia attuale) ha a sua volta una mappa verso
i 9 bucket "storici" del pool (``MAIN_CLASS_TO_LEGACY_BUCKET``): è il livello
usato quando la sottoclasse è incerta. Tutte e 15 le classi sono coperte,
scegliendo il bucket tematicamente più vicino (es. ``cibo``, ``musical_instrument``,
``kitchen_household``, ``tool_hardware``, ``accessory_misc`` -> ``"gioco di
imitazione"``, il gioco di ruolo/imitazione a cui questi oggetti appartengono
tipicamente). Questo elimina anche un bug del pool attuale: ``config.yaml``
puntava a un fallback finale ``"giocattolo"`` che non è mai stato una chiave
del pool, quindi falliva sempre in silenzio.

Uso::

    python tools/build_subject_map.py
    python tools/build_subject_map.py --pool "../lettura storie/stories2.json" --hierarchy models/hierarchy.json
    python tools/build_subject_map.py --out models/subject_map.json --report

Rieseguibile: se si aggiungono sottoclassi al dataset, si rilancia lo
script, si guarda il report per le nuove voci non coperte, e si aggiungono
eventuali override mancanti.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from difflib import get_close_matches
from pathlib import Path
from typing import Any

DEFAULT_HIERARCHY = Path(__file__).resolve().parent.parent / "models" / "hierarchy.json"
DEFAULT_POOL = (
    Path(__file__).resolve().parent.parent.parent / "lettura storie" / "stories2.json"
)
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "models" / "subject_map.json"

FUZZY_CUTOFF = 0.88

# ── Override espliciti: etichetta grezza (nome cartella) -> chiave del pool ──
# Solo i casi che NON sono identici dopo la normalizzazione (traduzioni,
# riordini, refusi del pool da rispettare, bucket generici molti-a-uno).
# Raggruppati per classe principale solo per leggibilità: la chiave usata a
# runtime resta l'etichetta grezza da sola (le poche etichette ripetute in
# più classi, es. "forchetta", puntano comunque alla stessa voce del pool).
SUBCLASS_OVERRIDES: dict[str, str] = {
    # accessory_misc
    # (nessun override: le uniche 3 coperte sono identiche dopo normalizzazione)
    # action_figure_cartoon
    "alieno": "alien",
    "bluey_cane_dei_cartoni_animati": "bluey toy",
    "fantasma": "ghost",
    "fata_magica": "fairy",
    "peppapig": "peppa pig",
    "robot_umanoide": "robot humanoid",
    "simpson": "the simpson",
    "sirena": "marmaid",  # refuso del pool (mermaid): si rispetta com'è
    "stitch_animalletto_combina_guai": "stitch",
    "supersonic": "super sonic",
    "tartarughe_ninja": "ninja turtle",
    "yoda_star_wars": "yoda",
    # action_figure_generic_historical
    "bambole": "doll",
    "darth_vader_starwars": "star wars",  # non c'e' una voce specifica per Darth Vader
    "luigi_idraulico": "luigi",
    "mago": "wizard",
    "nativi_americani": "native americans",
    "personaggi_lego_generici": "generic lego figure",
    "poliziotto": "policeman",
    "principessa_disney": "disney princess",
    "re": "king",
    "soldato_militare": "soldier military",
    "soldato_romano": "roman empire",
    "spiederman": "spiderman",  # refuso nell'etichetta del dataset
    "strega": "witch",
    "supermario": "super mario",
    # animal_dinosaur — nessuna specie ha una storia dedicata: bucket generico
    "brontosauro": "dinosaur",
    "drago": "dragon",
    "pterodattile": "dinosaur",
    "stegosauro": "dinosaur",
    "t-rex": "dinosaur",
    "triceratopo": "dinosaur",
    # animal_real
    "cane": "dog",
    "castoro": "beaver",
    "coniglio": "rabbit",
    "elefante": "elephant",
    "gatto": "cat",
    "papera": "duck",
    "pecora": "sheep",
    "pesce": "fish",
    "polipo": "octopus",
    "scimmia": "monkey",
    "serpente": "snake",
    "squalo": "shark",
    "uccello": "ucello",  # refuso del pool (manca una 'c'): si rispetta com'è
    "unicorno": "unicorn",
    "volpe": "fox",
    # cibo
    "lecca_lecca": "lollipop",
    # construction_building
    "casa_delle_bambole": "dollhouse",
    "casa_di_blocchi": "block house",
    "mucchio_di_blocchi": "building block",
    "statua_dell_liberta": "statue of liberty",
    "torre_eiffel": "eiffel tour",  # refuso del pool (tour invece di tower)
    # construction_puzzle_game
    "cubo_di_rubick": "rubick cube",
    "tangram": "tamgram",  # refuso del pool
    # electronic_and_robot
    "animale_robot": "robot pet",
    "braccio_robotico": "braccio robot",
    "robot_su_ruote": "robot on wheels",
    "tamagochi": "tamagotchi",
    # physical_activity
    "aquilone": "kite",
    "biglie": "marbles",
    "corda_per_saltare": "jump rope",
    "fresbee": "frisbee",  # refuso nell'etichetta del dataset
    "pistola_ad_acqua": "water gun",
    "trottola": "spinning toy",
    "yoyo": "yo yo",
    "palla_da_baseball": "ball",
    "palla_da_biliardo": "ball",
    "palla_da_bowling": "ball",
    "palla_da_calcio": "ball",
    "palla_da_golf": "ball",
    "palla_da_pallavolo": "ball",
    "palla_da_rugby": "ball",
    "palla_da_tennis": "ball",
    "palla_da_volano": "ball",
    # vehicle
    "aereoplani": "toy plane",
    "barca_a_motore": "toy boat",
    "barca_a_vela": "toy boat",
    "crociera": "toy boat",
    "gru_per_costruzioni": "gru",
    "macchina_di_formula_1": "formula 1",
    "macchinine": "toy car",
    "razzo": "rocket",
}

# ── Classe principale (15, tassonomia attuale) -> bucket storico del pool (9) ──
# Usata quando la sottoclasse e' incerta (<50%) ma la classe principale no.
# accessory_misc/cibo/kitchen_household/musical_instrument/tool_hardware non
# avevano equivalente nella vecchia tassonomia a 9 classi: sono oggetti
# tipici del gioco di imitazione (cucina giocattolo, travestimenti,
# strumenti/attrezzi finti), quindi confluiscono li'.
MAIN_CLASS_TO_LEGACY_BUCKET: dict[str, str] = {
    "accessory_misc": "gioco di imitazione",
    "action_figure_cartoon": "action figure",
    "action_figure_generic_historical": "action figure",
    "animal_dinosaur": "animale di peluche",
    "animal_real": "animale di peluche",
    "cibo": "gioco di imitazione",
    "construction_building": "gioco di costruzioni",
    "construction_nature_decor": "gioco di costruzioni",
    "construction_puzzle_game": "gioco da tavolo",
    "electronic_and_robot": "robot giocattolo",
    "kitchen_household": "gioco di imitazione",
    "musical_instrument": "gioco di imitazione",
    "physical_activity": "gioco da fare all'aperto",
    "tool_hardware": "gioco di imitazione",
    "vehicle": "veicolo giocattolo",
}

# Fallback di ultima istanza (classe principale anch'essa incerta, <55%).
# Sostituisce "giocattolo" in config.yaml, che non era mai una chiave del
# pool: quel fallback falliva sempre in silenzio (vedi story_cache.py).
FINAL_FALLBACK_SUBJECT = "gioco di imitazione"


def normalize(text: str) -> str:
    """Minuscolo, senza accenti, underscore/trattini -> spazio, spazi collassati."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("_", " ").replace("-", " ")
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def load_hierarchy(path: Path) -> dict[str, list[str]]:
    """{classe_principale: [sottoclassi grezze]} da hierarchy.json."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        main: list(spec.get("labels", []))
        for main, spec in data.get("subclassifiers", {}).items()
    }


def load_pool_keys(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    storie = data.get("storie", {})
    if not isinstance(storie, dict) or not storie:
        raise ValueError(f"{path} non contiene una sezione 'storie' valida")
    return list(storie.keys())


def match_subclass(
    raw_label: str, pool_keys: list[str], normalized_pool: dict[str, str]
) -> tuple[str | None, str]:
    """Ritorna (chiave_pool_o_None, metodo)."""
    if raw_label in SUBCLASS_OVERRIDES:
        candidate = SUBCLASS_OVERRIDES[raw_label]
        if candidate not in pool_keys:
            return None, f"override non valido (chiave assente dal pool: {candidate!r})"
        return candidate, "override"

    norm = normalize(raw_label)
    if norm in normalized_pool:
        return normalized_pool[norm], "normalizzazione esatta"

    close = get_close_matches(norm, normalized_pool.keys(), n=1, cutoff=FUZZY_CUTOFF)
    if close:
        return normalized_pool[close[0]], "fuzzy (DA VERIFICARE)"

    return None, "nessuna corrispondenza"


def build_map(hierarchy_path: Path, pool_path: Path) -> dict[str, Any]:
    hierarchy = load_hierarchy(hierarchy_path)
    pool_keys = load_pool_keys(pool_path)
    normalized_pool = {normalize(k): k for k in pool_keys}

    unknown_main = sorted(set(hierarchy) - set(MAIN_CLASS_TO_LEGACY_BUCKET))
    if unknown_main:
        raise ValueError(
            "Classi principali senza bucket storico in MAIN_CLASS_TO_LEGACY_BUCKET: "
            f"{unknown_main}. Aggiungile prima di rigenerare la mappa."
        )
    invalid_buckets = sorted(
        b for b in set(MAIN_CLASS_TO_LEGACY_BUCKET.values()) if b not in pool_keys
    )
    if invalid_buckets:
        raise ValueError(f"Bucket storici assenti dal pool: {invalid_buckets}")
    if FINAL_FALLBACK_SUBJECT not in pool_keys:
        raise ValueError(f"FINAL_FALLBACK_SUBJECT {FINAL_FALLBACK_SUBJECT!r} assente dal pool")

    subclass_map: dict[str, dict[str, Any]] = {}
    fuzzy_review: list[str] = []
    unmatched: list[str] = []

    for main_class, raw_labels in hierarchy.items():
        for raw_label in raw_labels:
            key = f"{main_class}/{raw_label}"
            pool_key, method = match_subclass(raw_label, pool_keys, normalized_pool)
            subclass_map[key] = {
                "raw_label": raw_label,
                "main_class": main_class,
                "pool_key": pool_key,
                "method": method,
            }
            if method.startswith("fuzzy"):
                fuzzy_review.append(f"{key} -> {pool_key!r}")
            if pool_key is None:
                unmatched.append(key)

    return {
        "subclass_to_story": subclass_map,
        "main_class_to_legacy_bucket": MAIN_CLASS_TO_LEGACY_BUCKET,
        "final_fallback_subject": FINAL_FALLBACK_SUBJECT,
        "pool_source": pool_path.name,
        "stats": {
            "total_subclasses": len(subclass_map),
            "matched": len(subclass_map) - len(unmatched),
            "unmatched": len(unmatched),
            "fuzzy_needs_review": len(fuzzy_review),
        },
        "_fuzzy_review": fuzzy_review,
        "_unmatched": unmatched,
    }


def print_report(result: dict[str, Any]) -> None:
    stats = result["stats"]
    print(
        f"\nSottoclassi totali: {stats['total_subclasses']}  "
        f"con storia dedicata: {stats['matched']}  "
        f"senza (ricadono sulla classe principale): {stats['unmatched']}"
    )
    if result["_fuzzy_review"]:
        print(f"\nCorrispondenze sfocate da verificare a mano ({len(result['_fuzzy_review'])}):")
        for line in result["_fuzzy_review"]:
            print(f"  ? {line}")
    print("\nMappa classe principale -> bucket generico (usata sotto il 50% di confidenza):")
    for main_class, bucket in result["main_class_to_legacy_bucket"].items():
        print(f"  {main_class:<35} -> {bucket}")
    print(f"\nFallback finale (classe principale incerta): {result['final_fallback_subject']!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hierarchy", type=Path, default=DEFAULT_HIERARCHY)
    parser.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--quiet", action="store_true", help="Non stampare il report, solo scrivere il file"
    )
    args = parser.parse_args()

    if not args.hierarchy.is_file():
        raise SystemExit(f"hierarchy.json non trovato: {args.hierarchy}")
    if not args.pool.is_file():
        raise SystemExit(f"Pool di storie non trovato: {args.pool}")

    result = build_map(args.hierarchy, args.pool)

    output = {k: v for k, v in result.items() if not k.startswith("_")}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Scritto: {args.out}")

    if not args.quiet:
        print_report(result)


if __name__ == "__main__":
    main()
