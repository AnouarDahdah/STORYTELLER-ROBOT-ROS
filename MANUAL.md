# Imaginarium ROS2 — Manuale d'uso

## 1. Funzione
Il sistema identifica un giocattolo con la fotocamera esistente, crea o riprende un profilo digitale persistente nel database SQLite e racconta una storia. Ogni riconoscimento aggiornato è memorizzato fra spegnimenti e riavvii. Il microfono registra 5 secondi e usa un modello Vosk offline se installato. ROS2 gestisce identificazione, profili, narrazione, audio e accensione/spegnimento come nodi separati.

## 2. Architettura
- `identification_node`: cattura/classifica e pubblica `toy/identified`.
- `digital_twin_node`: salva profili e conteggi in `~/imaginarium_twins.sqlite3` o nel database configurato.
- `storytelling_node`: risolve il soggetto, sceglie una storia dal pool e usa Piper/TTS.
- `microphone_node`: registra e trascrive offline con Vosk; pubblica `conversation/request`.
- `power_control_node` C++: pubblica `on`, `off` e `listen` su `device/power`.

## 3. Installa sul Raspberry Pi
Su Raspberry Pi OS Bookworm 64-bit: installa ROS 2 Humble o Jazzy compatibile con il proprio OS, quindi:

```bash
bash install_imaginarium.sh
sudo mkdir -p /var/lib/imaginarium
```

Scarica un modello Vosk italiano per `~/models/vosk`, ad esempio da Alphacephei. Senza modello il sistema continua a narrare ma la trascrizione vocale rimane disabilitata.

## 4. Avvio
```bash
cd ~/IMAGINARUIM-team-main_ros2/ros2_ws
source /opt/ros/humble/setup.bash   # oppure jazzy
source install/setup.bash
ros2 launch imaginarium_ros imaginarium.launch.py \
  config:=/opt/imaginarium/raspberry_story/config.yaml \
  database:=/var/lib/imaginarium/twins.sqlite3
```

## 5. Identificare e raccontare
```bash
# Scatta un nuovo giocattolo
ros2 topic pub --once /camera/request_identification std_msgs/String "{data: ''}"

# Oppure usa un'immagine esistente
ros2 topic pub --once /camera/request_identification std_msgs/String "{data: '/opt/imaginarium/raspberry_story/runtime/photos/toy.jpg'}"

# Registra una richiesta del bambino
ros2 topic pub --once /microphone/record_now std_msgs/String "{data: 'record'}"

# Interrogare i profili
sqlite3 /var/lib/imaginarium/twins.sqlite3 'select toy_id,story_count,session_count,last_seen from toys;'
```

## 6. Accensione e spegnimento
```bash
ros2 topic pub --once /device/control std_msgs/String "{data: 'on'}"
ros2 topic pub --once /device/control std_msgs/String "{data: 'listen'}"
ros2 topic pub --once /device/control std_msgs/String "{data: 'off'}"
```

I pulsanti fisici possono pubblicare gli stessi comandi tramite GPIO e il nodo C++ mantiene il controllo centralizzato.

## 7. Comandi utili
```bash
ros2 topic echo /toy/identified
ros2 topic echo /toy/profile
ros2 topic echo /toy/story_event
ros2 topic echo /story/status
ros2 node list
ros2 topic list
```

## 8. Test senza hardware
```bash
cd /opt/imaginarium/raspberry_story
python3 -m pytest
```

## 9. Sicurezza e privacy
- Audio registrato per 5 secondi è temporaneo e viene cancellato dopo la trascrizione.
- Il profilo usa una chiave locale derivata dal nome della sottoclasse; non invia dati a Internet.
- Vosk è offline. Nessun cloud o account è richiesto.
- Verifica che la telecamera e il microfono siano fisicamente rivolti verso il bambino in modo appropriato.

## 10. Smoke test eseguito su WSL / ROS2 Jazzy

Il workspace è stato compilato correttamente con `colcon build --symlink-install` su Ubuntu 24.04 WSL con ROS2 Jazzy.

Verifica rapida:

```bash
source /opt/ros/jazzy/setup.bash
source ~/imaginarium_ros2/ros2_ws/install/setup.bash
ros2 run imaginarium_ros digital_twin_node.py --ros-args -p database:=/tmp/imaginarium_smoke.sqlite3
```

In un secondo terminale:

```bash
source /opt/ros/jazzy/setup.bash
source ~/imaginarium_ros2/ros2_ws/install/setup.bash
python3 publish_identification.py
python3 inspect_smoke_db.py
```

Risultato verificato:
- Il nodo `digital_twin_node` riceve `toy/identified`.
- Il profilo `treno` viene salvato in SQLite.
- La seconda identificazione aumenta `session_count` da 1 a 2.
- Il nodo C++ `power_control_node` accetta `on`, `listen` e `off` su `/device/control`.

Nota: in WSL non è possibile accedere direttamente alla fotocamera, al microfono, agli altoparlanti o ai GPIO del Raspberry Pi. Il test WSL valida ROS graph, compilazione C++/Python e persistenza SQLite; il test hardware va eseguito sul Raspberry Pi.

## 11. Verifica dei dati mancanti

Prima di usare identificazione o sintesi vocale reale, eseguire:

```bash
cd raspberry_story
python tools/check_full_system_assets.py
```

Il risultato `[OK]` indica asset presente; `[MISSING]` indica un dato da trasferire dal progetto di sviluppo. Il formato completo delle cartelle e dei nomi attesi è descritto in `FULL_SYSTEM_DATA_REQUIRED.md`.

Lo stato attuale verificato nel pacchetto è:
- pool IT/EN/SL presenti
- TFLite hierarchy/model assenti
- subject map assente
- tre voci Piper assenti

In assenza di questi dati il sistema resta valido per smoke test ROS, profili digitali SQLite, controllo alimentazione e microfono senza trascrizione Vosk.

## 12. Latest live verification result

Live ROS verification on 2026-11-26 confirmed:
- `colcon build --symlink-install` succeeds.
- All five ROS nodes start in the launch file.
- `power_control_node` accepts `on`, `listen`, and `off`.
- Mock identification reaches `digital_twin_node`.
- SQLite stores one profile and one interaction for the mock `treno` toy.
- Unit tests pass: 25/25.
- Real TFLite identification remains unavailable because `models/hierarchy.json` and `model.tflite` are missing.
- Storytelling remains unavailable because `models/subject_map.json` and Piper voices are missing.
- This result validates ROS transport, degraded startup, power control, and persistent digital-twin storage—not real toy classification or spoken story playback.

## 13. Conversazione continuativa per bambino

Quando viene riconosciuto un giocattolo, il sistema:
1. aggiorna il profilo digitale persistente;
2. propone in voce una storia breve collegata al giocattolo;
3. attende una risposta positiva del bambino;
4. genera o seleziona una nuova storia solo dopo il consenso;
5. ruota fra amicizia, coraggio, collaborazione, curiosità, gentilezza e responsabilità;
6. evita di ripetere l’ultimo indice della storia quando sono disponibili alternative;
7. può collegare personaggi già incontrati nello stesso dispositivo.

Comandi test:

```bash
# Pubblica un profilo toy/profilo simulato
python3 publish_identification.py

# Risposte vocali simulabili via ROS2
ros2 topic pub --once /conversation/request std_msgs/msg/String "{data: 'sì, racconta'}"
ros2 topic pub --once /conversation/request std_msgs/msg/String "{data: 'no, un altra volta'}"
ros2 topic pub --once /conversation/request std_msgs/msg/String "{data: 'basta'}"

# Monitora proposta, racconto e eventi
ros2 topic echo /story/status
ros2 topic echo /toy/story_event
```

La scelta finale e le storie restano basate sul pool pre-generato fino all’aggiunta di un modello LLM locale controllato. Questo mantiene il sistema rapido, offline e adatto ai bambini.
