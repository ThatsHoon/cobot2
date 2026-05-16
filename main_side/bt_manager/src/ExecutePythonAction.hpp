#include <rclcpp/rclcpp.hpp>
#include <rclcpp_action/rclcpp_action.hpp>
#include <behaviortree_cpp_v3/action_node.h>
#include <string>

#include "command/action/command.hpp"

class ExecutePythonAction : public BT::AsyncActionNode {
private:
    rclcpp::Node::SharedPtr ros_node_;
    rclcpp_action::Client<command::action::Command>::SharedPtr action_client_;

public:
    ExecutePythonAction(const std::string& name, const BT::NodeConfiguration& config, rclcpp::Node::SharedPtr node)
        : BT::AsyncActionNode(name, config), ros_node_(node) {

        // Action Client 생성 (파이썬 executer.py의 액션 서버 이름과 맞춰주세요)
        action_client_ = rclcpp_action::create_client<command::action::Command>(ros_node_, "execute_command");
    }

    static BT::PortsList providedPorts() {
        return { 
            BT::InputPort<std::string>("action_name"),
            BT::InputPort<std::string>("target_name")
        };
    }

    BT::NodeStatus tick() override {
        std::string action;
        std::string target = "none"; // 기본값 (타겟이 없는 동작을 대비)

        if (!getInput<std::string>("action_name", action)) {
            RCLCPP_ERROR(ros_node_->get_logger(), "동작 이름(action_name)이 없습니다!");
            return BT::NodeStatus::FAILURE;
        }

        // 타겟 이름은 선택적으로 가져옵니다 (shake 등은 target이 없을 수 있음)
        getInput<std::string>("target_name", target);

        RCLCPP_INFO(ros_node_->get_logger(), "🤖 파이썬으로 명령 전송 준비: [Action: %s, Target: %s]", action.c_str(), target.c_str());

        // 1. executer.py가 파싱할 JSON 생성
        std::string json_cmd = "[{\"action\": \"" + action + "\", \"params\": {\"target\": \"" + target + "\"}}]";

        // 2. 서버 연결 대기
        if (!action_client_->wait_for_action_server(std::chrono::seconds(3))) {
            RCLCPP_ERROR(ros_node_->get_logger(), "❌ 파이썬 액션 서버(/execute_command)가 응답하지 않습니다.");
            return BT::NodeStatus::FAILURE;
        }

        // 3. 목표(Goal) 메시지 생성 및 전송
        auto goal_msg = command::action::Command::Goal();
        goal_msg.command = json_cmd; // 🚨 인터페이스의 실제 필드명(.action 파일)에 맞게 할당

        RCLCPP_INFO(ros_node_->get_logger(), "🚀 파이썬으로 동작 전송: %s", json_cmd.c_str());

        auto send_goal_options = rclcpp_action::Client<command::action::Command>::SendGoalOptions();
        auto goal_handle_future = action_client_->async_send_goal(goal_msg, send_goal_options);

        if (goal_handle_future.wait_for(std::chrono::seconds(5)) != std::future_status::ready) {
            RCLCPP_ERROR(ros_node_->get_logger(), "❌ 목표 전송 시간 초과");
            return BT::NodeStatus::FAILURE;
        }

        auto goal_handle = goal_handle_future.get();
        if (!goal_handle) {
            RCLCPP_ERROR(ros_node_->get_logger(), "❌ 파이썬 서버가 명령을 거부했습니다.");
            return BT::NodeStatus::FAILURE;
        }

        RCLCPP_INFO(ros_node_->get_logger(), "⏳ 로봇 제어 중... 파이썬의 완료 응답 대기...");

        // 4. 로봇의 물리적 동작이 끝날 때까지 결과 대기
        auto result_future = action_client_->async_get_result(goal_handle);
        result_future.wait(); // AsyncActionNode이므로 여기서 wait()를 걸어도 메인 스핀이 멈추지 않습니다!
        auto result = result_future.get();

        // 5. 최종 결과에 따라 BT 상태 반환
        if (result.code == rclcpp_action::ResultCode::SUCCEEDED) {
            RCLCPP_INFO(ros_node_->get_logger(), "✅ 로봇 동작 성공!");
            return BT::NodeStatus::SUCCESS;
        } else {
            RCLCPP_ERROR(ros_node_->get_logger(), "🚨 로봇 동작 중 에러/실패 발생!");
            return BT::NodeStatus::FAILURE;
        }
    }
};