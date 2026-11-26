from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    config = LaunchConfiguration('config')
    database = LaunchConfiguration('database')
    language = LaunchConfiguration('language')
    return LaunchDescription([
        DeclareLaunchArgument('config', default_value='/opt/imaginarium/raspberry_story/config.yaml'),
        DeclareLaunchArgument('database', default_value='/var/lib/imaginarium/twins.sqlite3'),
        DeclareLaunchArgument('language', default_value='it'),
        Node(package='imaginarium_ros', executable='identification_node.py', output='screen', parameters=[{'config': config}]),
        Node(package='imaginarium_ros', executable='digital_twin_node.py', output='screen', parameters=[{'database': database}]),
        Node(package='imaginarium_ros', executable='storytelling_node.py', output='screen', parameters=[{'config': config, 'language': language}]),
        Node(package='imaginarium_ros', executable='microphone_node.py', output='screen'),
        Node(package='imaginarium_ros', executable='power_control_node', output='screen'),
    ])
