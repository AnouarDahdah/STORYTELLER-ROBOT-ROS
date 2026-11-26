#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/string.hpp>

#include <cstdlib>
#include <cstdio>
#include <fstream>
#include <string>

class PowerControlNode : public rclcpp::Node {
public:
  PowerControlNode() : Node("power_control_node") {
    power_pub_ = this->create_publisher<std_msgs::msg::String>("device/power", 10);
    cmd_sub_ = this->create_subscription<std_msgs::msg::String>(
      "device/control", 10,
      [this](std_msgs::msg::String::SharedPtr msg) { handle_command(msg->data); });

    power_pin_ = this->declare_parameter("power_pin", 17);
    led_pin_ = this->declare_parameter("led_pin", 27);
    RCLCPP_INFO(this->get_logger(), "Power control ready. Publish 'on', 'off', or 'listen' to device/control.");
  }

private:
  void handle_command(const std::string& command) {
    std_msgs::msg::String event;
    if (command == "on") {
      event.data = "on";
      RCLCPP_INFO(this->get_logger(), "Device ON");
      set_gpio(power_pin_, 1);
    } else if (command == "off") {
      event.data = "off";
      RCLCPP_INFO(this->get_logger(), "Device OFF");
      set_gpio(power_pin_, 0);
    } else if (command == "listen") {
      event.data = "listen";
      RCLCPP_INFO(this->get_logger(), "Microphone listening requested");
    } else {
      RCLCPP_WARN(this->get_logger(), "Unknown power command: %s", command.c_str());
      return;
    }
    power_pub_->publish(event);
  }

  void set_gpio(int pin, int level) {
    char command[160];
    std::snprintf(command, sizeof(command), "gpioset gpiochip0 %d=%d >/dev/null 2>&1 || true", pin, level);
    std::system(command);
  }

  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr power_pub_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr cmd_sub_;
  int power_pin_{};
  int led_pin_{};
};

int main(int argc, char ** argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<PowerControlNode>());
  rclcpp::shutdown();
  return 0;
}
