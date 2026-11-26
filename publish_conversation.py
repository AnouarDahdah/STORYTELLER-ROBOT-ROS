import rclpy
from rclpy.node import Node
from std_msgs.msg import String
import time

rclpy.init()
node = Node("conversation_smoke_publisher")
pub = node.create_publisher(String, "/conversation/request", 10)
for text in ("sì, racconta", "no, non ora", "basta"):
    msg = String()
    msg.data = text
    time.sleep(0.5)
    pub.publish(msg)
    time.sleep(0.5)
node.destroy_node()
rclpy.shutdown()
