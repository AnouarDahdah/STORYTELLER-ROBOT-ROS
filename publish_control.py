import rclpy
from rclpy.node import Node
from std_msgs.msg import String
import time

rclpy.init()
node = Node("control_smoke_publisher")
pub = node.create_publisher(String, "/device/control", 10)
for command in ("on", "listen", "off"):
    msg = String()
    msg.data = command
    time.sleep(0.5)
    pub.publish(msg)
    time.sleep(0.5)
node.destroy_node()
rclpy.shutdown()
