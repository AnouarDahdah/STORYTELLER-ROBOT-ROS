#!/usr/bin/env python3

import json
import subprocess
import tempfile
from pathlib import Path

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class MicrophoneNode(Node):
    def __init__(self):
        super().__init__('microphone_node')
        self.declare_parameter('record_device', 'default')
        self.declare_parameter('record_seconds', 5.0)
        self.enabled = True
        self.create_subscription(String, 'device/power', self.power, 10)
        self.create_subscription(String, 'microphone/record_now', self.record_once, 10)
        self.pub = self.create_publisher(String, 'conversation/request', 10)

    def power(self, msg):
        self.enabled = msg.data != 'off'

    def record_once(self, msg):
        if not self.enabled:
            return
        device = str(self.get_parameter('record_device').value)
        duration = float(self.get_parameter('record_seconds').value)
        with tempfile.TemporaryDirectory() as td:
            wav = Path(td) / 'child.wav'
            cmd = ['arecord','-D',device,'-d',str(int(duration)),'-f','S16_LE','-r','16000','-c','1',str(wav)]
            try:
                subprocess.run(cmd, check=True, timeout=duration+10, capture_output=True)
            except Exception as exc:
                self.get_logger().error('Microphone failed: %s', exc)
                return
            try:
                from vosk import Model, KaldiRecognizer
                model_path = str(Path.home() / 'models' / 'vosk')
                if not Path(model_path).is_dir():
                    raise RuntimeError('No offline speech model at ~/models/vosk')
                import wave
                wf = wave.open(str(wav), 'rb')
                rec = KaldiRecognizer(Model(model_path), wf.getframerate())
                text = ''
                while True:
                    data = wf.readframes(4000)
                    if not data:
                        break
                    if rec.AcceptWaveform(data):
                        text += ' ' + json.loads(rec.Result()).get('text','')
                text += ' ' + json.loads(rec.FinalResult()).get('text','')
            except Exception as exc:
                text = ''
                self.get_logger().warn('Offline speech unavailable; use a story/status text command. %s', exc)
            out = String(); out.data=text.strip()
            self.pub.publish(out)


def main():
    rclpy.init()
    node=MicrophoneNode(); rclpy.spin(node)
    node.destroy_node(); rclpy.shutdown()

if __name__=='__main__':
    main()
