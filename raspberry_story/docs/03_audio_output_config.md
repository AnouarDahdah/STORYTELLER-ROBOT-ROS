# 3. Configurazione dell'uscita audio (stereo/amplificatore)

## 3.1 ALSA semplice, non PulseAudio/PipeWire

Raspberry Pi OS Lite non installa un server audio (PulseAudio/PipeWire) di
default, e per questo progetto è la scelta giusta da **non** cambiare:
`imaginarium/audio_io.py` parla direttamente con **ALSA** tramite
`arecord`/`aplay` (vedi il modulo, sezione "Come per la fotocamera..."). Un
server audio aggiungerebbe un livello (latenza, un servizio in più da tenere
in piedi, un altro punto di configurazione) per un beneficio che qui non
serve: **un solo processo alla volta** riproduce audio (una storia, o le
tre lingue del comando 1 in sequenza — mai in sovrapposizione), quindi non
c'è bisogno di missare più sorgenti, che è il problema che PulseAudio/PipeWire
risolvono. Se in futuro servisse (es. suoni di interfaccia sovrapposti alla
voce), si potrà riconsiderare.

## 3.2 Device di riproduzione di default

Dopo aver identificato il device dell'amplificatore (sezione 2.3-2.4 di
[`02_hardware_setup.md`](02_hardware_setup.md)), due modi per impostarlo:

**A — solo per questo progetto** (consigliato: non tocca la configurazione
di sistema, e coincide con quello che leggono i test manuali già presenti
nel repo, vedi `Configurazione webcam e modelli.txt`):

```yaml
# config.yaml
audio:
  playback_device: "hw:CARD=Device,DEV=0"   # il nome trovato con `aplay -L`
```

**B — device ALSA di default di sistema** (utile se vuoi che anche altri
programmi, non solo questa pipeline, usino l'amplificatore senza specificarlo):

```bash
cat <<'EOF' | sudo tee /etc/asound.conf
pcm.!default {
    type hw
    card "Device"     # il nome dopo CARD= trovato con `aplay -L`
}
ctl.!default {
    type hw
    card "Device"
}
EOF
```

Per questo progetto **A basta**: `config.yaml` è comunque la fonte di
verità per ogni device (camera, microfono, altoparlante), coerente con il
resto della configurazione.

## 3.3 Test rapido

```bash
speaker-test -D hw:CARD=Device,DEV=0 -c2 -t wav -l1
```

Un `-c2` (stereo) con `-t wav` riproduce un breve annuncio "front left" /
"front right" su ciascun canale: se senti solo un canale, o nessuno,
controlla il cablaggio dello stereo prima di guardare oltre nel software.
Ferma con `Ctrl+C`.

Test con lo stesso device/parametri usati dalla pipeline:

```bash
aplay -D hw:CARD=Device,DEV=0 /usr/share/sounds/alsa/Front_Center.wav
```

(quel file esiste di default su Raspberry Pi OS grazie ad `alsa-utils`; se
manca, genera un WAV di prova con `speaker-test` sopra e riproduci quello.)

## 3.4 Volume

```bash
alsamixer     # interfaccia interattiva: F6 per scegliere la scheda, frecce per il volume
# oppure, da riga di comando:
amixer -c 2 sset Speaker 80%      # 'Speaker' varia per dispositivo: `amixer -c 2 scontrols` li elenca
```

Il nome del controllo (`Speaker`, `PCM`, `Master`, ...) dipende dal chip
audio dell'amplificatore USB: `amixer -c <numero_card> scontrols` elenca
quelli disponibili per quella scheda specifica.

## 3.5 Troubleshooting "nessun suono"

Nell'ordine in cui vale la pena controllare:

1. **Il device esiste ancora con lo stesso nome?** `aplay -l`/`aplay -L`
   dopo ogni riavvio: se l'amplificatore è sparito dalla lista, è un
   problema di alimentazione/collegamento USB (torna a
   [`02_hardware_setup.md`](02_hardware_setup.md), sezione 2.1).
2. **Volume a zero o canale mutato?** `alsamixer`, verifica che non ci sia
   `MM` (muted) accanto al controllo — si sblocca con `m`.
3. **`aplay` restituisce un errore esplicito?** `imaginarium/audio_io.py`
   propaga lo `stderr` di `aplay` dentro `AudioError`: il messaggio (device
   occupato, formato non supportato, ...) è quasi sempre diagnostico da
   solo.
4. **Sottotensione?** `vcgencmd get_throttled` — se il risultato non è
   `throttled=0x0`, il Pi ha rilevato un problema di alimentazione in questa
   sessione (guarda i bit: `0x50000` per esempio segnala sottotensione
   avvenuta): torna alla sezione 2.1, l'hub deve essere alimentato.
5. **Formato/rate non supportato dal DAC dell'amplificatore?** `config.yaml`
   usa `S16_LE`/`48000 Hz`, supportato da qualunque DAC USB comune; se hai
   cambiato questi valori e il suono è distorto o assente, riportali ai
   default e riprova.

Una volta che `speaker-test`/`aplay` funzionano in modo affidabile, prossimo
passo: [`04_tts_setup.md`](04_tts_setup.md) per installare Piper e le 3 voci.
