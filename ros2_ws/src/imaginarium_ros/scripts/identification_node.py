#!/usr/bin/env python3

import json
import sys
from pathlib import Path

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class IdentificationNode(Node):
    def __init__(self):
        super().__init__('identification_node')
        self.declare_parameter('config', '/opt/imaginarium/raspberry_story/config.yaml')
        project_root = Path(str(self.get_parameter('config').value)).resolve().parent
        sys.path.insert(0, str(project_root))
        from imaginarium.cli import bootstrap
        from imaginarium.camera import capture_photo
        from imaginarium.inference import HierarchicalClassifier
        self.bootstrap = bootstrap
        self.capture_photo = capture_photo
        self.HierarchicalClassifier = HierarchicalClassifier

        self.config = self.bootstrap(str(self.get_parameter('config').value))
        self.classifier = None
        self.status_pub = self.create_publisher(String, 'identification/status', 10)
        try:
            self.classifier = self.HierarchicalClassifier.from_config(self.config)
            self.publish_status('ready', 'Classifier assets loaded')
        except Exception as exc:
            self.publish_status('degraded', f'Classifier unavailable: {exc}')
            self.get_logger().warn(str(exc))
        self.pub = self.create_publisher(String, 'toy/identified', 10)
        self.sub = self.create_subscription(String, 'camera/request_identification', self.identify, 10)
        self.power_sub = self.create_subscription(String, 'device/power', self.power, 10)
        self.enabled = True

    def power(self, msg):
        self.enabled = msg.data != 'off'

    def identify(self, msg):
        if not self.enabled:
            return
        if self.classifier is None:
            self.publish_status('degraded', 'Classifier assets missing; real identification unavailable')
            self.get_logger().warn('Classifier assets missing; real identification unavailable')
            return
        image = Path(msg.data) if msg.data else self.config.paths.photos_dir / 'ros2_toy.jpg'
        try:
            if not image.is_file():
                image = self.capture_photo(self.config.camera, image)
            result = self.classifier.classify(image)
            payload = {
                'image': str(image),
                'main_class': result.main_class,
                'main_confidence': result.main_confidence,
                'sub_class': result.sub_class,
                'sub_confidence': result.sub_confidence,
                'classification': result.to_dict(),
            }
            out = String()
            out.data = json.dumps(payload, ensure_ascii=False)
            self.pub.publish(out)
            self.get_logger().info('Identified %s / %s', payload['main_class'], payload['sub_class'])
        except Exception as exc:
            self.get_logger().error('Identification failed: %s', exc)

    def publish_status(self, status, message):
        msg = String()
        msg.data = json.dumps({'status': status, 'message': message}, ensure_ascii=False)
        self.status_pub.publish(msg)


def main():
    rclpy.init()
    node = IdentificationNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
