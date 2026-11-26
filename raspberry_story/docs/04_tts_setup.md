# 4. Sintesi vocale: Piper e le voci IT/EN/SL

I comandi 1/2/3 parlano in italiano, inglese e sloveno. Il motore è sempre
[Piper](https://github.com/rhasspy/piper) (stesso usato per l'italiano nella
versione precedente della pipeline): gira bene su CPU ARM, funziona offline,
e ha voci pronte per tutte e tre le lingue.

## 4.1 Installare Piper

```bash
cd Production
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt   # include piper-tts, che fornisce l'eseguibile `piper`
which piper                        # conferma che l'eseguibile è nel PATH del venv
```

## 4.2 Scaricare le 3 voci

Tutte da [huggingface.co/rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices),
qualità `medium` (buon compromesso qualità/velocità/peso su CPU ARM — vedi
nota in fondo per le alternative):

```bash
cd voices

# Italiano — Paola (già usata nella versione precedente)
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/it/it_IT/paola/medium/it_IT-paola-medium.onnx
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/it/it_IT/paola/medium/it_IT-paola-medium.onnx.json

# Inglese (US) — Lessac
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json

# Sloveno — Artur (unica voce slovena disponibile nel repository Piper)
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/sl/sl_SI/artur/medium/sl_SI-artur-medium.onnx
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/sl/sl_SI/artur/medium/sl_SI-artur-medium.onnx.json

cd ..
ls voices/   # devono comparire 6 file: 3 voci x (.onnx + .onnx.json)
```

> **Nota sullo sloveno.** A differenza di italiano e inglese (più voci/
> qualità disponibili), il progetto Piper offre **una sola voce slovena**
> (`artur`, solo qualità `medium`, maschile). Se in futuro Piper ne
> pubblicherà altre, la sezione `languages.sl` in `config.yaml` è l'unico
> punto da aggiornare (`voice_model`/`voice_config`). Un'alternativa per lo
> sloveno, se in futuro `artur` risultasse insoddisfacente, è
> [Coqui/MMS-TTS](https://huggingface.co/facebook/mms-tts-slv) (supporto
> sloveno più ampio ma engine diverso, richiederebbe adattare
> `imaginarium/tts.py`) — non necessaria oggi, ma è il punto da cui
> ripartire se servisse.

## 4.3 Collegare le voci a `config.yaml`

Sono già referenziate nella sezione `languages:` di `config.yaml` (vedi
anche [`../README.md`](../README.md)):

```yaml
languages:
  it:
    story_pool: runtime/stories_it.json
    voice_model: voices/it_IT-paola-medium.onnx
    voice_config: voices/it_IT-paola-medium.onnx.json
  en:
    story_pool: runtime/stories_en.json
    voice_model: voices/en_US-lessac-medium.onnx
    voice_config: voices/en_US-lessac-medium.onnx.json
  sl:
    story_pool: runtime/stories_sl.json
    voice_model: voices/sl_SI-artur-medium.onnx
    voice_config: voices/sl_SI-artur-medium.onnx.json
```

Se scarichi le voci con nomi/percorsi diversi, aggiorna questi 6 valori di
conseguenza — non serve toccare altro codice: ogni lingua eredita
motore/timeout/prosodia dalla sezione `tts:` globale (vedi
`imaginarium/config.py`, `LanguageConfig`).

## 4.4 Test

Un test isolato per lingua (usa `imaginarium/tts.py` con la voce di quella
lingua, stesso codice dei comandi):

```bash
python test_tts.py "Ciao, sono un test!"                       # usa tts.voice_model di default (IT)
```

`test_tts.py` di per sé testa solo la sezione `tts:` globale (una voce): per
verificare le **3 lingue** insieme, il modo più diretto è lanciare
direttamente un comando reale una volta pronti anche modelli e pool di
storie (vedi [`05_modelli_e_storie.md`](05_modelli_e_storie.md)):

```bash
python run_button.py 1 --image runtime/photos/test_camera.jpg --stats
```

che sintetizza e riproduce in sequenza IT, EN, SL, stampando anche quanto ci
mette ciascuna sintesi (`sintesi_it`, `sintesi_en`, `sintesi_sl` nei tempi
per fase).

## 4.5 Prestazioni attese

Piper (a differenza del vecchio percorso con Ollama) è **rapido anche su
CPU ARM**: qualità `medium` sintetizza tipicamente più veloce del tempo di
riproduzione (real-time o meglio) su un Pi 4. Il comando 1, che sintetizza
3 lingue in sequenza, resta quindi nell'ordine dei secondi totali, non dei
minuti — la parte più lenta della pipeline è ormai la classificazione
TFLite, non più la voce. Se vuoi misurarlo con numeri: `monitor_stats.py`
in un secondo terminale mentre lanci `run_button.py --stats` (vedi
[`07_monitoraggio_risorse.md`](07_monitoraggio_risorse.md)).
