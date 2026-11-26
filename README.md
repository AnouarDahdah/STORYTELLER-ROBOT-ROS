# Imaginarium — ROS2 Interactive Toy Storytelling

Imaginarium is an educational, offline-first storytelling system for a Raspberry Pi. It combines toy identification, persistent digital-twin profiles, conversational interaction, pre-generated child-safe stories and text-to-speech into a ROS2 node architecture.

## Features

- ROS2 Jazzy/Humble-compatible node architecture
- Toy image capture and hierarchical TFLite identification
- Persistent SQLite profiles for every recognized toy
- Device-level conversation continuity
- Seen-toy companion references across stories
- Rotating child-friendly themes: friendship, courage, collaboration, curiosity, kindness and responsibility
- Explicit child consent before starting a story
- Italian, English and Slovenian story pools
- Offline Piper text-to-speech
- Offline Vosk speech recognition support
- C++ power-control node for device and GPIO commands
- Degraded startup behavior when model or voice assets are not yet installed

## Architecture

```text
Camera
  -> identification_node
  -> toy/identified
  -> digital_twin_node
  -> toy/profile
  -> storytelling_node
  -> speaker / story/status / toy/story_event

microphone_node -> conversation/request -> storytelling_node
power_control_node -> device/power -> all nodes
```

### Nodes

- `identification_node`: captures or accepts an image and runs hierarchical TFLite classification.
- `digital_twin_node`: creates and updates persistent toy profiles in SQLite.
- `storytelling_node`: remembers the active toy and seen companions, asks for consent, rotates narrative themes and plays stories.
- `microphone_node`: records brief child speech and transcribes it with an optional Vosk model.
- `power_control_node`: handles `on`, `off` and `listen` commands, plus optional GPIO output.

## Repository layout

```text
MANUAL.md                         Detailed installation and operation manual
FULL_SYSTEM_DATA_REQUIRED.md      Exact external model/voice asset requirements
raspberry_story/                  Existing Python story and inference application
ros2_ws/src/imaginarium_ros/      ROS2 package, launch file and nodes
publish_identification.py         ROS smoke-test profile publisher
publish_conversation.py           ROS child-consent simulator
publish_control.py                ROS on/listen/off publisher
inspect_pipeline_db.py            SQLite profile inspector
install_imaginarium.sh            Raspberry Pi installer
```

## Quick start: Raspberry Pi

The target OS is Raspberry Pi OS Bookworm 64-bit. Install ROS2 Humble or Jazzy according to the installed OS, then:

```bash
cd ~
bash install_imaginarium.sh
sudo mkdir -p /var/lib/imaginarium
```

See `MANUAL.md` for hardware, ALSA, camera, Piper and Vosk setup.

## Quick start: WSL smoke test

The smoke test validates ROS graph communication and SQLite persistence without Raspberry Pi hardware.

```bash
source /opt/ros/jazzy/setup.bash
source ~/imaginarium_ros2/ros2_ws/install/setup.bash

ros2 launch imaginarium_ros imaginarium.launch.py \
  config:=/home/anouar/imaginarium_ros2/raspberry_story/config.yaml \
  database:=/tmp/imaginarium_pipeline_test.sqlite3
```

In a second terminal:

```bash
source /opt/ros/jazzy/setup.bash
source ~/imaginarium_ros2/ros2_ws/install/setup.bash

python3 publish_identification.py
python3 publish_control.py
python3 publish_conversation.py
python3 inspect_pipeline_db.py
```

## Observe live topics

```bash
ros2 node list
ros2 topic list

ros2 topic echo /device/power
ros2 topic echo /toy/profile
ros2 topic echo /toy/story_event
ros2 topic echo /story/status
ros2 topic echo /conversation/request
```

Send power commands:

```bash
ros2 topic pub --once /device/control std_msgs/msg/String "{data: 'on'}"
ros2 topic pub --once /device/control std_msgs/msg/String "{data: 'listen'}"
ros2 topic pub --once /device/control std_msgs/msg/String "{data: 'off'}"
```

Send simulated child consent:

```bash
ros2 topic pub --once /conversation/request std_msgs/msg/String "{data: 'sì, racconta'}"
ros2 topic pub --once /conversation/request std_msgs/msg/String "{data: 'no, non ora'}"
ros2 topic pub --once /conversation/request std_msgs/msg/String "{data: 'basta'}"
```

## Missing assets

Real toy identification and spoken stories require external files. Check readiness:

```bash
cd raspberry_story
python tools/check_full_system_assets.py
```

Required assets are described in `FULL_SYSTEM_DATA_REQUIRED.md`:

- `models/hierarchy.json`
- TFLite classifier model files
- `models/subject_map.json`
- Italian, English and Slovenian story pools
- Three Piper ONNX voices and their JSON metadata
- Optional Italian Vosk speech model

Without these assets, ROS transport, persistent digital twins and power controls can still be tested.

## Tests

```bash
cd raspberry_story
python3 -m pytest -q
python3 -m compileall -q imaginarium tools ../ros2_ws/src/imaginarium_ros
python tools/check_full_system_assets.py
```

Current verified result:

- 29 Python unit tests pass
- ROS2 package builds with `colcon`
- All nodes and live topics start in degraded mode when assets are missing
- Mock identification persists a SQLite digital twin
- Power controls publish `on`, `listen` and `off`

## Safety and privacy

- Microphone recordings are temporary and limited to five seconds by default.
- Vosk speech recognition is offline.
- No child audio or profile is sent to a cloud service by the source package.
- The system uses pre-generated child-suitable stories until a local, safety-controlled generation backend is added.
- Child consent is required before a story starts.

## Documentation

- `MANUAL.md`: complete operating manual
- `FULL_SYSTEM_DATA_REQUIRED.md`: exact model and voice file layout
- `raspberry_story/README.md`: original Python pipeline documentation
- `raspberry_story/docs/`: Raspberry Pi installation and hardware guides

