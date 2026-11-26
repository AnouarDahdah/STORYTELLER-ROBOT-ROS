# 1. Installazione del sistema operativo sul Raspberry Pi 4

## Quale immagine scegliere

**Raspberry Pi OS Lite a 64 bit (Bookworm)**, senza desktop.

Perché:

- **Nessuna GUI necessaria.** L'interazione con il dispositivo finale è a
  pulsanti fisici (per ora, da tastiera/CLI: vedi
  [`06_comandi_e_workflow.md`](06_comandi_e_workflow.md)): un desktop
  grafico userebbe RAM e CPU senza che nessuno lo guardi mai. Su un Pi 4 da
  4 GB, con TFLite (classificazione) e Piper (sintesi vocale, 3 voci
  caricate) che devono girare senza intoppi, ogni centinaio di MB libero in
  più conta.
- **64 bit, non 32.** Le wheel precompilate di `tflite-runtime` e delle
  librerie numeriche (`numpy`) per Raspberry Pi sono pubblicate per aarch64;
  su un OS a 32 bit si finisce quasi sempre a compilare da sorgente, lento e
  fragile. Un Pi 4 (tutti i modelli, incluso il 2 GB) supporta il 64 bit
  senza eccezioni.
- **Bookworm** (l'attuale release stabile) porta **Python 3.11**, la stessa
  versione già usata sul PC di sviluppo per questo progetto (si vede dai
  `__pycache__/*.cpython-311.pyc` nel repo): nessuna sorpresa di
  compatibilità nel passaggio dev → device.
- **Non serve Raspberry Pi OS "Full"** (con LibreOffice, editor, ecc.): a
  meno di voler sviluppare/debuggare *direttamente sullo schermo del Pi*
  (sconsigliato: si lavora meglio da un altro PC via SSH), Lite basta e
  avanza.

## 1.1 Flashare la scheda SD con Raspberry Pi Imager

1. Scarica **Raspberry Pi Imager** da
   [raspberrypi.com/software](https://www.raspberrypi.com/software/) (Windows,
   macOS o Linux — puoi farlo dallo stesso PC di sviluppo).
2. Inserisci una microSD (consigliati almeno 32 GB: i modelli TFLite, 3 voci
   Piper e ~10 MB di storie multilingua occupano poco, ma vale la pena avere
   margine per log/foto/audio generati a runtime).
3. Apri Imager:
   - **Dispositivo**: Raspberry Pi 4.
   - **Sistema operativo**: `Raspberry Pi OS (other)` → `Raspberry Pi OS
     Lite (64-bit)`.
   - **Archiviazione**: la tua microSD.
4. Clicca l'icona a ingranaggio (**Impostazioni avanzate**, oppure `Ctrl+Shift+X`)
   **prima di scrivere** — è il modo per avere un dispositivo pronto all'uso
   al primo boot, senza monitor/tastiera collegati (setup "headless"):
   - **Abilita SSH** → "Usa autenticazione a password" (più semplice da
     ricordare) oppure carica la tua chiave pubblica.
   - **Imposta nome utente e password**.
   - **Configura WLAN**: SSID + password della rete Wi‑Fi (se non userai un
     cavo Ethernet), e imposta il **paese Wi‑Fi** corretto (es. `IT`) — senza
     questo il modulo Wi‑Fi resta disattivato per motivi regolatori.
   - **Impostazioni locali**: fuso orario e layout tastiera.
   - Salva, poi clicca **Scrivi**. Imager scarica l'immagine, la scrive e la
     verifica (10-20 minuti a seconda della connessione/SD).

## 1.2 Primo boot e accesso SSH

1. Inserisci la microSD nel Pi 4, collega l'alimentazione (**alimentatore
   USB-C ufficiale da 5V/3A**: un alimentatore sottodimensionato causa
   sottotensione intermittente, che sui log appare come `Under-voltage
   detected` e può far comportare in modo strano proprio USB/audio, cioè
   l'hardware di cui parla [`02_hardware_setup.md`](02_hardware_setup.md)).
2. Attendi 1-2 minuti per il primo avvio, poi da un altro PC sulla stessa
   rete:

   ```bash
   ssh <utente>@raspberrypi.local
   ```

   Se `raspberrypi.local` non risolve (dipende dal router), trova l'IP dalla
   pagina di amministrazione del router o con uno scanner di rete, e usa
   `ssh <utente>@<ip>`.

## 1.3 Primo aggiornamento e configurazione di base

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

Poi apri lo strumento di configurazione:

```bash
sudo raspi-config
```

- **3 Interface Options** → **Camera**: se la webcam è UVC (USB, la
  quasi totalità delle webcam esterne), non serve abilitare nulla qui
  (l'interfaccia CSI del Pi è un'altra cosa) — la webcam USB verrà rilevata
  come `/dev/videoN` senza configurazione aggiuntiva, vedi
  [`02_hardware_setup.md`](02_hardware_setup.md).
- **1 System Options** → **Boot / Auto Login** → resta su console, nessun
  autologin necessario (il dispositivo non ha schermo collegato in uso
  normale).
- **6 Advanced Options** → **Expand Filesystem**: di norma già fatto al
  primo boot da Raspberry Pi OS stesso; se `df -h /` mostra la partizione
  root più piccola della SD, forzalo da qui.
- Esci e riavvia se richiesto.

## 1.4 Prestazioni: governor della CPU

Il governor di default (`ondemand` o `schedutil`) scala la frequenza della
CPU in base al carico, introducendo latenza variabile — irrilevante per un
uso interattivo generico, ma rende **il tempo della classificazione TFLite
meno prevedibile** da un comando all'altro. Fissarlo a `performance` toglie
questa variabile (costo: consumo/calore leggermente più alti, non un
problema per un dispositivo sempre alimentato):

```bash
sudo apt install -y cpufrequtils
echo 'GOVERNOR="performance"' | sudo tee /etc/default/cpufrequtils
sudo systemctl restart cpufrequtils
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor   # deve stampare: performance
```

## 1.5 Swap

Un Pi 4 da 2 GB con 3 voci Piper caricate (IT/EN/SL) più il modello TFLite
può avvicinarsi al limite di RAM durante il comando 1 (le tre sintesi in
sequenza). Verifica quanta swap è configurata:

```bash
free -h
cat /proc/sys/vm/swappiness
```

Raspberry Pi OS configura di default 100-200 MB di swap su file
(`/var/swap`, gestita da `dphys-swapfile`) — sufficiente come margine di
sicurezza, ma **andare in swap in modo sistematico è un sintomo da
correggere**, non una soluzione: una microSD è lenta e si usura. Se
`monitor_stats.py` (vedi [`07_monitoraggio_risorse.md`](07_monitoraggio_risorse.md))
mostra swap usata stabilmente durante i comandi, il rimedio è un Pi 4 con
più RAM (4 GB consigliati, 2 GB al limite) piuttosto che allargare la swap.

## 1.6 Pacchetti di sistema richiesti dalla pipeline

```bash
sudo apt install -y v4l-utils alsa-utils git python3-venv python3-pip
```

- `v4l-utils` → `v4l2-ctl`, usato da `imaginarium/camera.py` per scattare.
- `alsa-utils` → `arecord`/`aplay`/`alsamixer`, usati da `imaginarium/audio_io.py`
  e per la configurazione audio (vedi [`03_audio_output_config.md`](03_audio_output_config.md)).
- `git` per clonare/aggiornare il repo (o `scp`/`rsync` se preferisci copiare
  senza Git sul dispositivo finale).

A questo punto il sistema operativo è pronto. Prossimo passo:
[`02_hardware_setup.md`](02_hardware_setup.md) per collegare camera e
amplificatore USB tramite l'hub.
