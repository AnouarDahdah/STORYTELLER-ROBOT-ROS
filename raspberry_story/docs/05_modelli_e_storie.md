# 5. Modelli, mappa soggetti e pool di storie

Tre cose vanno popolate in `Production/` prima che i comandi funzionino:
il classificatore (`models/`), la mappa soggetti (`models/subject_map.json`)
e i pool di storie multilingua (`runtime/stories_it.json`/`_en.json`/`_sl.json`).
Tutte e tre vanno preparate **sul PC di sviluppo** (o comunque non sul Pi:
la prima richiede TensorFlow, la terza può richiedere ore di generazione con
un LLM) e poi copiate sul dispositivo.

## 5.1 Modello di classificazione (`models/`)

Dal repository di sviluppo `toy_classifier/` (non su questo device: lì c'è
l'ambiente conda con TensorFlow):

```bash
cd toy_classifier
python sync_to_production.py
```

Esporta l'intera gerarchia in TFLite INT8 e copia in `Production/models/`
solo `hierarchy.json` + `model.tflite` + `labels.json` per ogni
classificatore (main + sottoclassificatori) — vedi
[`../README.md`](../README.md), sezione 1, per le opzioni (`--skip-export`,
`--dest`). Poi copia l'intera cartella `Production/` sul Pi:

```bash
scp -r Production/ pi@raspberrypi.local:~/
```

## 5.2 Mappa soggetti (`models/subject_map.json`)

Il classificatore riconosce etichette grezze (nomi di cartella del dataset,
es. `tartarughe_ninja`); il pool di storie usa chiavi scelte a mano in
un'altra lingua (es. `"ninja turtle"`). `tools/build_subject_map.py` collega
le due cose — vedi la docstring del file per i dettagli del metodo
(override espliciti, normalizzazione, fuzzy matching come rete di
sicurezza). Va rieseguito **ogni volta che il dataset guadagna nuove
sottoclassi** (nuovo modello da `toy_classifier`):

```bash
python tools/build_subject_map.py
```

Il report stampato a schermo mostra:

- quante sottoclassi hanno una storia dedicata nel pool, e quante ricadono
  sul bucket della classe principale (atteso: circa 6 su 10, il pool attuale
  non copre tutte le 294 sottoclassi — vedi 5.4);
- eventuali corrispondenze "fuzzy" (trovate per similarità, non per
  normalizzazione esatta o override esplicito) marcate **DA VERIFICARE**: se
  compaiono, controllale a mano e aggiungi un override esplicito in
  `SUBCLASS_OVERRIDES` (nel file) se la corrispondenza è sbagliata.

Il file prodotto va copiato sul Pi insieme al resto di `Production/` (è
dentro `models/`, quindi la `scp -r` della sezione 5.1 lo include già se
rilanciata dopo aver generato la mappa).

## 5.3 Pool di storie multilingua (`runtime/stories_it.json` / `_en.json` / `_sl.json`)

Il pool "di riferimento" di questo progetto è
`lettura storie/stories2.json` (1730 storie, 173 soggetti — le 9 macro-classi
storiche più 164 sottoclassi), già tradotto in inglese e sloveno in
`lettura storie/stories2_en.json` / `stories2_sl.json` (vedi
`Traduzione storie/translate_stories.py`: la traduzione preserva l'ordine
per soggetto, così la storia N in una lingua è la storia N nelle altre —
è ciò che rende possibile il comando 1 e il comando 3, vedi
[`06_comandi_e_workflow.md`](06_comandi_e_workflow.md)).

Sono già copiati in `Production/runtime/` con i nomi attesi da
`config.yaml`:

```bash
cp "lettura storie/stories2.json"    Production/runtime/stories_it.json
cp "lettura storie/stories2_en.json" Production/runtime/stories_en.json
cp "lettura storie/stories2_sl.json" Production/runtime/stories_sl.json
```

Rilanciala solo se rigeneri/estendi il pool sul PC di sviluppo (sezione 5.4)
e vuoi portare l'aggiornamento sul Pi.

## 5.4 Colmare i buchi di copertura (opzionale, offline)

Il pool attuale copre 173 soggetti su un totale di 294 sottoclassi + 15
classi principali. Cinque classi principali della tassonomia attuale
(`cibo`, `kitchen_household`, `musical_instrument`, `tool_hardware`,
`accessory_misc`) non esistevano nella tassonomia con cui il pool è stato
generato: oggi, per queste, `subjects.py` ricade sul bucket
`"gioco di imitazione"` (una scelta tematica ragionevole — sono tutti
oggetti tipici del gioco di ruolo/imitazione — ma generica, vedi
`tools/build_subject_map.py` per il ragionamento). Per dare a queste classi
storie proprie, e per aumentare la copertura delle sottoclassi non ancora
mappate (elencate come "nessuna corrispondenza" nel report di
`build_subject_map.py`), usa gli strumenti già presenti nel repo — **su un
PC, non sul Pi**: generare con un LLM anche solo poche decine di storie può
richiedere da minuti a ore a seconda del modello.

```bash
cd "lettura storie"

# --out punta al pool esistente con --append, cosi' si aggiunge invece di
# creare il default stories4.json. --model/--backend: qualunque modello gia'
# in uso per questo pool (qui Ollama con gemma3:4b, vedi generation/config.py
# per i preset disponibili).
python pregenerate_stories.py --backend ollama --model gemma3:4b \
    --subject cibo --per-subject 8 --preset quality --out stories2.json --append
python pregenerate_stories.py --backend ollama --model gemma3:4b \
    --subject "utensili da cucina" --per-subject 8 --preset quality --out stories2.json --append
python pregenerate_stories.py --backend ollama --model gemma3:4b \
    --subject "strumento musicale" --per-subject 8 --preset quality --out stories2.json --append
python pregenerate_stories.py --backend ollama --model gemma3:4b \
    --subject attrezzi --per-subject 8 --preset quality --out stories2.json --append
python pregenerate_stories.py --backend ollama --model gemma3:4b \
    --subject accessori --per-subject 8 --preset quality --out stories2.json --append

# poi, dalla cartella Traduzione storie/:
cd "../Traduzione storie"
python translate_stories.py "../lettura storie/stories2.json" --lang en --output "../lettura storie/stories2_en.json"
python translate_stories.py "../lettura storie/stories2.json" --lang sl --output "../lettura storie/stories2_sl.json"
```

(`pregenerate_stories.py` qui è quello di `lettura storie/`, non l'omonimo
in `Production/`: usa il backend `llama.cpp`/Ollama del repo di sviluppo, non
il pacchetto `imaginarium`. Vedi `lettura storie/README.md` per i dettagli e
le opzioni `--backend llama_cpp --model gguf_models/....gguf` se preferisci
generare in locale senza Ollama.)

`translate_stories.py` riprende da dove interrotto (vedi il suo `--help`):
rilanciarlo dopo aver aggiunto nuovi soggetti a `stories2.json` traduce solo
le storie nuove, non ritraduce quelle già fatte. Dopo, ripeti la copia della
sezione 5.3 e, sul Pi, rilancia `build_subject_map.py` (sezione 5.2) se hai
anche aggiunto sottoclassi lato modello.

## 5.5 Verifica finale

```bash
python tools/build_subject_map.py --quiet   # rigenera senza il report lungo
python -m pytest                              # test di logica (subjects, cache, stato)
python run_button.py 1 --image runtime/photos/test_camera.jpg --stats
```

Prossimo passo: [`06_comandi_e_workflow.md`](06_comandi_e_workflow.md) per
il dettaglio dei 3 comandi.
