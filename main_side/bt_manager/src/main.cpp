#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/string.hpp>
#include <behaviortree_cpp_v3/bt_factory.h>
#include <ament_index_cpp/get_package_share_directory.hpp>
#include <nlohmann/json.hpp>
#include <algorithm>

using json = nlohmann::json;

#include "PopNextTask.hpp"
#include "IsTargetRequired.hpp"
#include "ExecutePythonAction.hpp"
#include "IsTargetLocated.hpp"
#include "IsObjectGripped.hpp"
#include "IsResetAction.hpp"

int main(int argc, char **argv) {
    rclcpp::init(argc, argv);
    auto ros_node = std::make_shared<rclcpp::Node>("bt_manager");

    BT::BehaviorTreeFactory factory;

    factory.registerNodeType<PopNextTask>("PopNextTask");
    factory.registerNodeType<IsTargetRequired>("IsTargetRequired");
    factory.registerNodeType<IsTargetLocated>("IsTargetLocated"); 
    factory.registerNodeType<IsObjectGripped>("IsObjectGripped"); 
    factory.registerNodeType<IsResetAction>("IsResetAction");
    
    BT::NodeBuilder execute_builder = [ros_node](const std::string& name, const BT::NodeConfiguration& config) {
        return std::make_unique<ExecutePythonAction>(name, config, ros_node);
    };
    factory.registerBuilder<ExecutePythonAction>("ExecutePythonAction", execute_builder);

    std::string pkg_share = ament_index_cpp::get_package_share_directory("bt_manager");
    std::string xml_path = pkg_share + "/config/bt_cobot2.xml";
    
    auto tree = factory.createTreeFromFile(xml_path);
    tree.rootBlackboard()->set("llm_json", "");
    tree.rootBlackboard()->set("estop_flag", false);

    // BT 일시정지를 위한 제어 플래그
    bool is_paused = false;

    // 외부 명령 수신용 Subscriber (LLM)
    auto subscription = ros_node->create_subscription<std_msgs::msg::String>(
        "/voice_command", 10,
        [&tree, ros_node](const std_msgs::msg::String::SharedPtr msg) {
            RCLCPP_INFO(ros_node->get_logger(), "📨 외부 명령 수신! BT 블랙보드 업데이트...");
            tree.rootBlackboard()->set("llm_json", msg->data);
        });

    // 관리자 UI 명령(E-STOP/UNLOCK) 수신용 Subscriber 추가
    auto admin_sub = ros_node->create_subscription<std_msgs::msg::String>(
        "/admin_command", 10,
        [&tree, ros_node](const std_msgs::msg::String::SharedPtr msg) {
            json data = json::parse(msg->data);
            std::string cmd = data.value("command", "");
            if (cmd == "ESTOP") {
                RCLCPP_FATAL(ros_node->get_logger(), "🛑 비상 정지! 시퀀스 리셋 준비.");
                tree.rootBlackboard()->set("estop_flag", true); // 💡 BT에 리셋 지시
            }
        });

    auto status_pub = ros_node->create_publisher<std_msgs::msg::String>("/status", 10);

    RCLCPP_INFO(ros_node->get_logger(), "🌳 Behavior Tree 대기 모드 시작...");

    rclcpp::Rate rate(10); // 10Hz
    BT::NodeStatus status = BT::NodeStatus::IDLE;

    while (rclcpp::ok()) {
        // 💡 3. 일시정지 상태가 아닐 때만 트리를 동작시킵니다.
        if (!is_paused) {
            status = tree.tickRoot();
        }

        std::string action = "none";
        std::string target = "none";
        try { action = tree.rootBlackboard()->get<std::string>("action"); } catch (...) {}
        try { target = tree.rootBlackboard()->get<std::string>("target"); } catch (...) {}

        json payload;
        // 멈춰있을 땐 도커 화면에 PAUSED로 띄워줌
        payload["state"]  = is_paused ? "PAUSED" : BT::toStr(status);
        payload["action"] = action;
        payload["target"] = target;

        std_msgs::msg::String ros_msg;
        ros_msg.data = payload.dump();
        status_pub->publish(ros_msg);

        rclcpp::spin_some(ros_node);
        rate.sleep();
    }

    RCLCPP_INFO(ros_node->get_logger(), "🏁 Behavior Tree 실행 종료. 최종 상태: %s", BT::toStr(status).c_str());
    rclcpp::shutdown();
    return 0;
}