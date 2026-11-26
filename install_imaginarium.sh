#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$PROJECT_DIR/raspberry_story"
DST="/opt/imaginarium"

sudo mkdir -p "$DST" /var/lib/imaginarium
sudo rsync -a --delete "$SRC/" "$DST/raspberry_story/"
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip v4l-utils alsa-utils python3-colcon-common-extensions

cd "$DST"
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r raspberry_story/requirements.txt vosk

cd "$PROJECT_DIR/ros2_ws"
source /opt/ros/jazzy/setup.bash 2>/dev/null || source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash
mkdir -p ~/.imaginarium
printf 'Installation complete. Download a Vosk language model to ~/models/vosk before microphone use.\n'
