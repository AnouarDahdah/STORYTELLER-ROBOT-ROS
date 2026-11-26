# 7. Monitorare CPU/RAM mentre si provano i comandi

## 7.1 Uso interattivo veloce: `htop`/`btop`

Per un'occhiata immediata, senza scrivere né leggere nulla:

```bash
sudo apt install -y htop      # oppure: btop, interfaccia più moderna
htop
```

Apri un secondo terminale SSH (oltre a quello dove lanci `run_button.py`),
lancia `htop` e guardalo mentre nell'altro terminale esegui un comando: si
vede in tempo reale quali core si saturano (la classificazione TFLite è
multi-thread, la sintesi Piper generalmente mono-thread) e se la RAM si
avvicina al limite. Zero configurazione, ma nessuna registrazione: va bene
per un controllo al volo, non per confrontare misure fra un test e l'altro.

## 7.2 `monitor_stats.py`: letture leggibili e loggabili

Per qualcosa di più mirato a *questo* progetto — e specificamente per
correlare i tempi per fase che `run_button.py --stats` stampa con quello che
succede a CPU/RAM/temperatura nello stesso momento:

```bash
# terminale 1
python monitor_stats.py --interval 1

# terminale 2, mentre il primo gira
python run_button.py 1 --image runtime/photos/test_camera.jpg --stats
```

Output di `monitor_stats.py`, una riga per lettura:

```
ora         CPU%   per-core                     RAM                       SWAP%   temp°C
14:32:01    23.5%    45   12   38   19          812/3906 MB (20.8%)        0.0%    52.3
14:32:02    88.1%    95   91   87   79          891/3906 MB (22.8%)        0.0%    54.1
```

- **CPU% / per-core**: la media e il dettaglio dei 4 core del Pi 4. Un picco
  su un solo core durante "classificazione" è il comportamento atteso
  (TFLite non parallelizza sempre su tutti i thread per un modello di
  queste dimensioni); un picco su tutti e 4 durante "sintesi" indicherebbe
  che Piper sta usando più thread.
- **RAM**: usata/totale. Con 3 voci Piper caricate e il classificatore, su
  un Pi 4 da 2 GB vale la pena guardarla con attenzione (vedi
  [`01_installazione_os.md`](01_installazione_os.md), sezione 1.5, sullo
  swap).
- **temp°C**: temperatura della SoC (`vcgencmd measure_temp`, o
  `/sys/class/thermal/thermal_zone0/temp` come fallback se `vcgencmd` non è
  disponibile). Sopra ~80°C il Pi 4 inizia a ridurre la frequenza da solo
  (throttling termico): se la vedi arrivarci durante un uso normale, il
  case ha bisogno di più ventilazione.

## 7.3 Registrare una sessione su file

```bash
python monitor_stats.py --csv runtime/bench/stats.csv --interval 0.5
```

Il CSV (append, non sovrascrive: puoi accumulare più sessioni) si apre in
qualunque foglio di calcolo o con `pandas` per confrontare, ad esempio, il
comando 1 (3 sintesi in sequenza) col comando 2 (una sola). Ferma con
`Ctrl+C`: il file resta scritto fino a quel momento.

## 7.4 Lettura incrociata con `run_button.py --stats`

`run_button.py --stats` (vedi [`06_comandi_e_workflow.md`](06_comandi_e_workflow.md))
stampa i secondi per fase (`scatto`, `classificazione`, `scelta_storia`,
`sintesi_it`/`sintesi_en`/`sintesi_sl`, `riproduzione_it`/...). Messo
accanto a `monitor_stats.py` che gira nello stesso intervallo, si risponde
a domande tipo: "la classificazione è lenta perché la CPU è satura, o
perché sta aspettando I/O (caricamento del modello da SD)?" — nel primo
caso il CPU% sale durante quella fase, nel secondo no.
