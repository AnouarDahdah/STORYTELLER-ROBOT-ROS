# 2. Collegamento hardware: hub USB, webcam, amplificatore stereo

Configurazione target: **Raspberry Pi 4 Model B** → **hub USB** → **webcam**
(video + spesso anche microfono) e **amplificatore/stereo USB** (uscita
audio), entrambi collegati all'hub, l'hub collegato a una delle porte USB
del Pi.

## 2.1 Perché un hub USB *alimentato*

Le porte USB del Pi 4 erogano corrente da un budget condiviso limitato (il
Pi stesso, con SD, eventuale HAT, ecc., già assorbe parte dei ~1.2 A totali
tipicamente disponibili sulle porte USB). Una webcam UVC con sensore/LED più
un amplificatore USB con il proprio DAC possono, insieme, superare quel
budget — il sintomo tipico è un dispositivo che si disconnette/riconnette a
intermittenza, o che nei log (`dmesg`) mostra `usb 1-1: device descriptor
read/64, error -71` o simili, oppure il Pi stesso mostra il fulmine giallo
di sottotensione.

**Usa un hub USB alimentato** (con il proprio alimentatore a muro): l'hub
allora alimenta webcam e amplificatore dalla propria fonte, e il Pi vede
solo il traffico dati. Non è opzionale se i due dispositivi assieme
richiedono più di quanto il Pi possa dare — ed è comunque la scelta più
robusta anche quando "sembra funzionare" senza, perché toglie una causa
intermittente difficile da diagnosticare in seguito.

## 2.2 Collegamento fisico

1. Alimentatore dell'hub nella presa, hub acceso.
2. Webcam USB → una porta dell'hub.
3. Amplificatore/stereo USB → un'altra porta dell'hub.
4. Hub → una porta USB **3.0** del Pi 4 (quelle blu all'interno del
   connettore, sulla stessa fila delle porte Ethernet/USB — il Pi 4 ne ha
   due USB 3.0 e due USB 2.0; preferisci una 3.0 per l'hub, soprattutto se
   la webcam scatta a 1920x1080 MJPG come da `config.yaml`).

## 2.3 Identificare i device

Dopo il collegamento:

```bash
lsusb
```

Dovresti vedere due righe nuove (webcam + amplificatore), oltre all'hub
stesso. Serve per confermare che il Pi *vede* entrambi i dispositivi prima
di cercare i device Linux specifici sotto.

### Webcam → `/dev/videoN`

```bash
v4l2-ctl --list-devices
```

Una webcam UVC espone tipicamente **più** device (`/dev/video0`,
`/dev/video1`, ...): uno è il flusso video vero, gli altri sono metadata o
canali secondari. Verifica quale supporta la risoluzione/formato richiesti
da `config.yaml` (`1920x1080`, `MJPG`):

```bash
v4l2-ctl -d /dev/video0 --list-formats-ext
```

Cerca `MJPG` con `1920x1080` fra i formati elencati; se `/dev/video0` non lo
supporta, prova `/dev/video1`, ecc. Il device giusto va in
`config.yaml` → `camera.device`.

Test di scatto rapido (lo stesso comando che usa `imaginarium/camera.py`):

```bash
v4l2-ctl -d /dev/video0 --set-fmt-video=width=1920,height=1080,pixelformat=MJPG \
    --stream-mmap --stream-count=1 --stream-to=test.jpg
```

### Amplificatore/stereo → device ALSA

```bash
aplay -l    # dispositivi di riproduzione
arecord -l  # dispositivi di registrazione (se la webcam ha anche un microfono)
```

Output tipo:

```
card 2: Device [USB Audio Device], device 0: USB Audio [USB Audio]
```

Il numero dopo `card` è quello che finisce in `config.yaml` come `hw:2,0`
(vedi anche [`03_audio_output_config.md`](03_audio_output_config.md) per la
configurazione completa e per un modo più stabile di riferirsi al device).

## 2.4 Il problema della numerazione instabile

`card 2`/`card 3` sono assegnati **nell'ordine in cui Linux rileva i
device**, che dipende dall'ordine di enumerazione USB — a sua volta
influenzato da: ordine di accensione, porta dell'hub usata, persino tempi di
inizializzazione leggermente diversi fra un boot e l'altro. **Non è
garantito che l'amplificatore resti sempre `card 2` dopo un riavvio.**
`config.yaml` con `hw:2,0` scritto "a fuoco" oggi può puntare al device
sbagliato domani.

Due modi per renderlo stabile, dal più semplice al più robusto:

**Opzione A — riferirsi al device per nome invece che per indice.**
`aplay -L`/`arecord -L` (maiuscola, non `-l`) elencano gli stessi device con
identificatori più lunghi ma **legati al nome del prodotto USB**, stabili
anche se l'indice numerico cambia:

```bash
aplay -L | grep -A1 "^hw:"
```

Cerca una riga tipo `hw:CARD=Device,DEV=0` (il nome dopo `CARD=` viene dal
descrittore USB dell'amplificatore) e usala in `config.yaml` al posto di
`hw:2,0`:

```yaml
audio:
  playback_device: "hw:CARD=Device,DEV=0"
```

Funziona finché il nome del prodotto è unico fra i device collegati (il
caso normale con una sola webcam + un solo amplificatore).

**Opzione B — regola udev, se serve il massimo controllo** (utile solo se
in futuro colleghi due dispositivi USB audio identici, dove l'opzione A non
basta più a distinguerli): una regola in `/etc/udev/rules.d/` che assegna un
nome ALSA fisso in base al `idVendor`/`idProduct`/numero di porta USB
fisica. Fuori dallo scopo di questa guida rapida; se ti serve, `udevadm info
-a -n /dev/snd/controlC2` mostra gli attributi da usare per scrivere la
regola.

Per questo progetto, **l'opzione A è sufficiente** ed è quella usata negli
esempi di [`03_audio_output_config.md`](03_audio_output_config.md).

## 2.5 Dopo il collegamento

Prossimo passo: [`03_audio_output_config.md`](03_audio_output_config.md)
per impostare volumi e device di default, poi
[`04_tts_setup.md`](04_tts_setup.md) per le voci Piper. Una volta pronti
entrambi, `python test_camera.py` e `python test_audio.py` (nella root di
`Production/`) verificano l'hardware end-to-end con lo stesso codice usato
dai comandi reali.
