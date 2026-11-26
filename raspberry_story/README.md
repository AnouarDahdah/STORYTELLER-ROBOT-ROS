# Imaginarium — Production

Pipeline di produzione per il Raspberry Pi 4: **scatta una foto di un
giocattolo → lo classifica → racconta una storia pre-generata → la legge ad
alta voce**, in italiano, inglese e sloveno.

```
foto (webcam) → classificazione (TFLite) → storia (pool pre-generato, IT/EN/SL) → voce (Piper) → stereo
```

Questa cartella è pensata per stare **sul dispositivo finale**: a
differenza del repo di sviluppo (`toy_classifier/`), qui non c'è
TensorFlow, non c'è training, non ci sono notebook — solo ciò che serve a
eseguire i comandi con un footprint leggero per un Pi 4. **Nessun modello di
linguaggio gira sul dispositivo**: le storie sono pre-generate e già
tradotte, pescate da un pool a runtime (millisecondi, non minuti) — vedi
sezione "I 3 comandi" sotto.

## Guide dettagliate

Dal sistema operativo vuoto al dispositivo funzionante, in ordine:

1. [`docs/01_installazione_os.md`](docs/01_installazione_os.md) — Raspberry Pi OS Lite 64-bit, setup headless, prestazioni.
2. [`docs/02_hardware_setup.md`](docs/02_hardware_setup.md) — hub USB, webcam, amplificatore stereo.
3. [`docs/03_audio_output_config.md`](docs/03_audio_output_config.md) — ALSA, volumi, troubleshooting audio.
4. [`docs/04_tts_setup.md`](docs/04_tts_setup.md) — Piper e le 3 voci (IT/EN/SL), con i link di download.
5. [`docs/05_modelli_e_storie.md`](docs/05_modelli_e_storie.md) — popolare `models/`, la mappa soggetti, i pool di storie.
6. [`docs/06_comandi_e_workflow.md`](docs/06_comandi_e_workflow.md) — i 3 comandi in dettaglio, oggi da CLI, domani da pulsante fisico.
7. [`docs/07_monitoraggio_risorse.md`](docs/07_monitoraggio_risorse.md) — CPU/RAM/temperatura mentre si testano i comandi.

Questo README resta come riferimento rapido per struttura, quick start e i
comandi di sviluppo (banco di prova della generazione, cambio modello,
ampliamento del pool).

---

## Struttura

```
Production/
├── config.yaml               # tutta la configurazione: device, modelli, lingue, voce
├── requirements.txt
├── run_button.py              # CLI principale: i 3 comandi (foto -> storia -> audio)
├── run_pipeline.py            # percorso storico a singola lingua via Ollama (dev/opzionale)
├── monitor_stats.py           # monitor CPU/RAM/temperatura (vedi docs/07)
├── bench_story.py             # banco di prova della sola generazione testuale (dev/Ollama)
├── pregenerate_stories.py     # costruisce un pool a singola lingua (dev/Ollama)
├── test_camera.py / test_audio.py / test_tts.py / test_classify.py   # test isolati hardware
├── models/                    # hierarchy.json + model.tflite + subject_map.json
├── voices/                    # 3 voci Piper (.onnx + .onnx.json, da scaricare)
├── runtime/                   # pool di storie (permanenti) + foto/audio generati (effimeri)
├── tools/
│   └── build_subject_map.py   # etichetta grezza -> chiave del pool (vedi docs/05)
├── tests/                     # test di logica pura (pytest), nessun hardware richiesto
└── imaginarium/                # package applicativo
    ├── config.py                # config.yaml -> dataclass tipizzate (incluse le lingue)
    ├── exceptions.py
    ├── camera.py                 # scatto foto (v4l2-ctl)
    ├── audio_io.py                # registrazione/riproduzione (arecord/aplay)
    ├── subjects.py                 # classificazione -> chiave del pool (soglie 50%/55%)
    ├── story_cache.py              # pool di storie, anche multilingua sincronizzato per indice
    ├── state.py                    # stato "ultima storia" (comando 2 -> comando 3)
    ├── commands.py                  # i 3 comandi (run_button.py)
    ├── tts.py                       # sintesi vocale (Piper)
    ├── sysmon.py                    # statistiche di sistema (monitor_stats.py)
    ├── story.py / pipeline.py / presets.py   # percorso storico Ollama (dev/opzionale)
    └── inference/                    # classificazione gerarchica (TFLite)
        ├── registry.py
        ├── predictor.py
        └── hierarchical.py
```

Il design ricalca quello di `toy_classifier/toyclf` nel repo di sviluppo
(stessa idea: config centralizzata, moduli a responsabilità singola,
eccezioni tipizzate) — se conosci già quel repo, questo ti sarà familiare.

---

## Quick start

Presuppone sistema operativo, hardware e audio già pronti (guide 1-3 sopra).

```bash
# 1. dipendenze
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. voci Piper (IT/EN/SL) — vedi docs/04_tts_setup.md per i link esatti
#    scaricarle in voices/

# 3. modello di classificazione, dal PC di sviluppo (repo toy_classifier):
#    python sync_to_production.py   ->  poi copia Production/ qui (scp -r)

# 4. mappa soggetti (rigenerala se il modello cambia)
python tools/build_subject_map.py

# 5. pool di storie multilingua: già in runtime/stories_it.json / _en.json / _sl.json
#    (copie di lettura storie/stories2*.json — vedi docs/05 per i dettagli/aggiornamenti)

# verifica: test isolati, poi un comando reale
python test_camera.py
python test_audio.py
python test_tts.py "Ciao, sono un test!"
python run_button.py 1 --stats
```

Se qualcosa fallisce, il messaggio d'errore indica il rimedio più probabile
(device sbagliato, pacchetto mancante, file non trovato, pool incompleto,
...) — ogni eccezione è tipizzata per fase (`imaginarium/exceptions.py`).

---

## I 3 comandi

```bash
python run_button.py 1                    # scatta, racconta la stessa storia in IT, EN, SL
python run_button.py 2 --lang it           # scatta, racconta solo in italiano (o --lang en/sl)
python run_button.py 3                     # "traduce" (dal pool) l'ultima storia del comando 2

python run_button.py 1 --image foto.jpg    # salta lo scatto, usa un'immagine esistente
python run_button.py 2 --lang en --no-play # sintetizza ma non riproduce
python run_button.py 1 --stats --json      # tempi per fase, riepilogo JSON
```

Dettagli — come si sceglie il soggetto della storia in base alla confidenza
del classificatore, perché nessuno dei tre chiama un modello di linguaggio,
come si aggancerà in futuro a dei pulsanti fisici — in
[`docs/06_comandi_e_workflow.md`](docs/06_comandi_e_workflow.md).

Da Python (lo stesso punto d'ingresso che userà un futuro listener GPIO):

```python
from imaginarium.cli import bootstrap
from imaginarium.commands import run_command_1, run_command_2, run_command_3

config = bootstrap(None)
result = run_command_1(config)
print(result.stories["it"].text)
print(result.timings)
```

## Monitorare le risorse durante i test

```bash
python monitor_stats.py --interval 1              # in un secondo terminale, mentre provi i comandi
python monitor_stats.py --csv runtime/bench/stats.csv
```

Dettagli in [`docs/07_monitoraggio_risorse.md`](docs/07_monitoraggio_risorse.md)
(incluso l'uso di `htop`/`btop` per un controllo interattivo senza scrivere codice).

## Test

```bash
python -m pytest
```

Copre `subjects.py` (soglie e mappa), `story_cache.py` (pesca multilingua
sincronizzata per indice, fallback, personalizzazione del nome), `state.py`
(collegamento comando 2 → comando 3) e l'orchestrazione dei 3 comandi con
hardware sostituito da dei fake. Non copre camera/audio/TFLite reali: per
quelli servono i test manuali (`test_camera.py`, `test_audio.py`,
`test_tts.py`, `test_classify.py`) e l'hardware vero.

---

## Sviluppo: generazione delle storie (Ollama, opzionale)

Tutto quanto segue **non serve per usare i 3 comandi** (che pescano sempre
dal pool pre-generato, vedi sopra): resta per chi vuole generare **nuove**
storie o sperimentare con la generazione live, sul PC di sviluppo o su un
Pi usato anche per quello. Il codice qui è un porting quasi diretto di
`toyclf/story.py` del repo di sviluppo, adattato a modelli piccoli via
Ollama.

### Dipendenze aggiuntive

```bash
ollama pull gemma3:4b
ollama serve   # se non già attivo come servizio
```

### Pipeline a singola lingua con generazione live

```bash
python run_pipeline.py                     # scatta, classifica, racconta, riproduce (IT, via Ollama)
python run_pipeline.py --image foto.jpg     # salta lo scatto, usa un'immagine esistente
python run_pipeline.py --show-plan          # mostra anche lo scheletro narrativo
python run_pipeline.py --show-prompt        # mostra il prompt inviato al modello
python run_pipeline.py --stats              # tempi per fase e statistiche di generazione
python run_pipeline.py --no-cache           # ignora il pool, forza la generazione con Ollama
python run_pipeline.py --json               # riepilogo finale in JSON
```

### Banco di prova della generazione (`bench_story.py`)

Sul Pi 4 il collo di bottiglia di una generazione live è la banda di
memoria: il tempo scala quasi linearmente con i token generati e con la
taglia del modello. `bench_story.py` misura la sola parte testuale — niente
webcam, niente classificatore, niente audio:

```bash
python bench_story.py --list-presets
python bench_story.py --dry-run --show-prompt          # guarda i prompt senza chiamare il modello
python bench_story.py --preset baseline --repeat 3      # misura di riferimento
python bench_story.py --preset baseline --preset single_pass --preset fast --repeat 3
python bench_story.py --model gemma3:1b --preset fast --repeat 3
python bench_story.py --all-classes --preset fast --json runtime/bench/fast.json
```

`--show-prompt` mostra il prompt effettivo, `--seed 42` rende le
generazioni riproducibili (indispensabile per confrontare la *qualità*),
`--repeat 3` usa la mediana (un Pi4 basta un processo di sistema a produrre
un valore anomalo). I preset (`short`, `single_pass`, `lenient`, `threads`,
`small_ctx`, `fast`, `quality`, `tiny`, `tiny_two_pass`, ...) isolano una
leva alla volta o le combinano — vedi `imaginarium/presets.py` per la
descrizione di ciascuno. Quando una configurazione convince, i suoi valori
vanno ricopiati in `config.yaml` (sezione `story:`).

Leve fuori dal codice che pesano sulla misura:

```bash
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor   # 'performance', vedi docs/01
ollama ps                                                    # thread/RAM usati davvero
```

### Cambiare modello generativo

`gemma3:4b` non è vincolante: qualunque modello Ollama va bene
(`story.ollama_model` in `config.yaml`, o `--model` al banco di prova).

| Modello | Taglia su disco (~) | Note |
|---|---|---|
| `gemma3:4b` | ~3,3 GB | l'attuale. Su un Pi4 da 4 GB è al limite: controlla lo swap |
| `qwen2.5:3b` | ~1,9 GB | buona aderenza alle istruzioni e al JSON, italiano discreto |
| `llama3.2:3b` | ~2,0 GB | l'italiano è fra le lingue ufficialmente supportate |
| `gemma3:1b` | ~0,8 GB | stessa famiglia dell'attuale: il salto di velocità più grande |
| `qwen2.5:1.5b` | ~1,0 GB | spesso il migliore della categoria sul JSON strutturato |
| `llama3.2:1b` | ~1,3 GB | alternativa a gemma3:1b, da confrontare sul campo |

```bash
ollama pull gemma3:1b
python bench_story.py --preset baseline --preset tiny --repeat 3 --seed 42
```

**Attenzione alla RAM**: su un Pi 4 da 4 GB un modello da 3+ GB lascia poco
margine e può finire in swap sulla microSD (`ollama ps` per la RAM occupata,
`free -h` durante una generazione per verificare lo swap).

### Ampliare il pool di storie multilingua

Il pool usato dai 3 comandi (`runtime/stories_it.json`/`_en.json`/`_sl.json`)
va costruito ed esteso con gli strumenti in `lettura storie/` e
`Traduzione storie/`, non con `pregenerate_stories.py` di questa cartella
(che produce un pool a singola lingua per il percorso storico
`run_pipeline.py`) — vedi
[`docs/05_modelli_e_storie.md`](docs/05_modelli_e_storie.md), sezione 5.4,
per i comandi esatti.

---

## Cose da verificare sul campo

- **Precisione della classificazione su foto "reali" del Pi.** Il modello è
  stato addestrato su `benchmark_images/`; controlla che le foto scattate con
  `v4l2-ctl` (angolazione, luce, distanza) diano risultati comparabili —
  altrimenti rivedi `min_main_confidence`/`min_sub_confidence` in
  `config.yaml` per essere più prudenti quando il classificatore sbaglia
  (le stesse soglie usate da `imaginarium/subjects.py` per i 3 comandi).
- **Copertura del pool.** `python tools/build_subject_map.py` stampa quante
  sottoclassi hanno una storia dedicata; vedi
  [`docs/05_modelli_e_storie.md`](docs/05_modelli_e_storie.md) per colmare
  i buchi.
- **Latenza totale di un comando.** `python run_button.py 1 --stats` mostra
  i secondi per fase; con il pool pre-generato la fase "scelta_storia" è
  ormai trascurabile — la classificazione TFLite e le 3 sintesi Piper
  dominano il tempo totale.

## Orchestrazione

Questa cartella espone solo l'esecuzione manuale (`run_button.py`), come
richiesto: nessun servizio in background, nessun trigger automatico
(pulsante/voce) ancora collegato. Il punto di ingresso per un trigger fisico
futuro è `imaginarium.commands.run_command_1/2/3` — richiamabile da
qualunque script di supervisione (es. un listener GPIO o un servizio
systemd) senza toccare la logica dei comandi. Vedi
[`docs/06_comandi_e_workflow.md`](docs/06_comandi_e_workflow.md).

## ROS2 edge runtime

Questa distribuzione include un workspace ROS2 in `../ros2_ws` con nodi per identificazione, narrazione, profili digitali persistenti, microfono e accensione/spegnimento. Le istruzioni complete sono in `../MANUAL.md`.

## Full-system asset readiness

Before real identification or TTS works, transfer the external model and voice assets described in `../FULL_SYSTEM_DATA_REQUIRED.md`. Check readiness with:

```bash
python tools/check_full_system_assets.py
```

The existing story pools are included. TFLite hierarchy/model files, subject map and Piper voices are not present in this source package.
