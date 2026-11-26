import rclpy
from rclpy.node import Node
from std_msgs.msg import String
import json
import time

rclpy.init()
node = Node("smoke_publisher")
pub = node.create_publisher(String, "/toy/identified", 10)
payload = {
    "image": "test.jpg",
    "main_class": "vehicle",
    "main_confidence": 0.91,
    "sub_class": "treno",
    "sub_confidence": 0.87,
}
msg = String()
msg.data = json.dumps(payload)
time.sleep(1)
pub.publish(msg)
time.sleep(1)
node.destroy_node()
rclpy.shutdown()
