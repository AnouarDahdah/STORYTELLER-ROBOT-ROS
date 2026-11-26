#!/usr/bin/env python3

import json
import sqlite3
import threading
from pathlib import Path

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class DigitalTwinNode(Node):
    def __init__(self):
        super().__init__('digital_twin_node')
        self.declare_parameter('database', str(Path.home() / 'imaginarium_twins.sqlite3'))
        self.db_path = Path(self.get_parameter('database').value)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self._init_db()
        self.profile_pub = self.create_publisher(String, 'toy/profile', 10)
        self.create_subscription(String, 'toy/identified', self.on_identified, 10)
        self.create_subscription(String, 'toy/story_event', self.on_story_event, 10)

    def _init_db(self):
        with sqlite3.connect(self.db_path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS toys (
                toy_id TEXT PRIMARY KEY, main_class TEXT, sub_class TEXT,
                profile_json TEXT, first_seen TEXT, last_seen TEXT,
                story_count INTEGER DEFAULT 0, session_count INTEGER DEFAULT 0
            )''')
            db.execute('''CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, toy_id TEXT, event_type TEXT,
                payload TEXT, timestamp TEXT
            )''')

    def on_identified(self, msg):
        data = json.loads(msg.data)
        main = data['main_class']
        sub = data.get('sub_class') or main
        toy_id = sub if data.get('sub_confidence', 0) >= 0.50 else main
        profile = {
            'toy_id': toy_id,
            'main_class': main,
            'sub_class': sub,
            'last_image': data.get('image'),
            'confidence': {'main': data['main_confidence'], 'sub': data.get('sub_confidence')},
        }
        with self.lock, sqlite3.connect(self.db_path) as db:
            row = db.execute('SELECT profile_json,story_count,session_count FROM toys WHERE toy_id=?', (toy_id,)).fetchone()
            if row:
                old = json.loads(row[0])
                old.update(profile)
                profile = old
                story_count, sessions = row[1], row[2] + 1
            else:
                story_count, sessions = 0, 1
            db.execute('''INSERT INTO toys(toy_id,main_class,sub_class,profile_json,first_seen,last_seen,story_count,session_count)
                VALUES(?,?,?,?,datetime('now'),datetime('now'),?,?)
                ON CONFLICT(toy_id) DO UPDATE SET main_class=excluded.main_class,sub_class=excluded.sub_class,
                profile_json=excluded.profile_json,last_seen=datetime('now'),story_count=excluded.story_count,session_count=excluded.session_count''',
                (toy_id, main, sub, json.dumps(profile, ensure_ascii=False), story_count, sessions))
            db.execute('INSERT INTO interactions(toy_id,event_type,payload,timestamp) VALUES(?,?,?,datetime("now"))',
                       (toy_id, 'identified', json.dumps(profile, ensure_ascii=False)))
        out = String(); out.data = json.dumps(profile, ensure_ascii=False); self.profile_pub.publish(out)

    def on_story_event(self, msg):
        data = json.loads(msg.data)
        toy_id = data.get('toy_id')
        if not toy_id:
            return
        with self.lock, sqlite3.connect(self.db_path) as db:
            db.execute('INSERT INTO interactions(toy_id,event_type,payload,timestamp) VALUES(?,?,?,datetime("now"))',
                       (toy_id, data.get('event_type', 'story'), json.dumps(data, ensure_ascii=False)))
            if data.get('event_type') == 'story_started':
                db.execute('UPDATE toys SET story_count=story_count+1,last_seen=datetime("now") WHERE toy_id=?', (toy_id,))


def main():
    rclpy.init()
    node = DigitalTwinNode()
    rclpy.spin(node)
    node.destroy_node(); rclpy.shutdown()

if __name__ == '__main__':
    main()
