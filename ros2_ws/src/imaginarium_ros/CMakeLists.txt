cmake_minimum_required(VERSION 3.8)
project(imaginarium_ros)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclpy REQUIRED)
find_package(std_msgs REQUIRED)

add_executable(power_control_node src/power_control_node.cpp)
ament_target_dependencies(power_control_node rclcpp std_msgs)

ament_python_install_package(imaginarium_ros)
install(TARGETS power_control_node DESTINATION lib/${PROJECT_NAME})
install(PROGRAMS
  scripts/identification_node.py
  scripts/storytelling_node.py
  scripts/digital_twin_node.py
  scripts/microphone_node.py
  DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY launch config DESTINATION share/${PROJECT_NAME})
ament_package()
