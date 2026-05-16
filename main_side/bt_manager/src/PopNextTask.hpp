#include <behaviortree_cpp_v3/action_node.h>
#include <queue>
#include <string>
#include <iostream>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

struct Task {
    std::string action;
    std::string target;
};

class PopNextTask : public BT::ActionNodeBase {
private:
    std::queue<Task> task_queue_;

public:
    PopNextTask(const std::string& name, const BT::NodeConfiguration& config)
        : BT::ActionNodeBase(name, config) {}

    static BT::PortsList providedPorts() {
        return { 
            BT::InputPort<std::string>("llm_json"), 
            BT::InputPort<bool>("estop_flag"), // 💡 비상정지 플래그 입력
            BT::OutputPort<std::string>("action_name"),
            BT::OutputPort<std::string>("target_name")
        };
    }

    BT::NodeStatus tick() override {
        // 비상 정지 플래그 확인 -> 큐 전면 소각 (Flush)
        bool estop = false;
        if (getInput<bool>("estop_flag", estop) && estop) {
            std::cout << "🚨 [PopNextTask] 비상 정지 감지! 큐에 남은 모든 작업을 소각합니다.\n";
            while(!task_queue_.empty()) task_queue_.pop(); // 큐 비우기
            
            config().blackboard->set("estop_flag", false); // 플래그 끄기
            
            // 더 이상 할 일이 없으므로 대기 상태 반환
            setOutput("action_name", std::string("none"));
            setOutput("target_name", std::string("none"));
            return BT::NodeStatus::RUNNING; 
        }

        // 새로운 LLM 명령 확인 (동일 명령 연속 무시 문제 해결)
        std::string json_str;
        if (getInput<std::string>("llm_json", json_str) && !json_str.empty()) {
            // 블랙보드를 즉시 비워서 다음번에 똑같은 명령이 와도 받을 수 있게 함
            config().blackboard->set("llm_json", std::string("")); 
            
            try {
                json j_array = json::parse(json_str);
                while(!task_queue_.empty()) task_queue_.pop();

                task_queue_.push({"reset", "none"}); // 안전을 위한 초기화 동작 추가
                for (const auto& item : j_array) {
                    Task t;
                    t.action = item["action"];
                    t.target = (item.contains("params") && item["params"].contains("target")) ? item["params"]["target"] : "none";
                    task_queue_.push(t);
                }
                std::cout << "[PopNextTask] ✅ 새 명령 시퀀스(총 " << task_queue_.size() << "개) 수신 완료.\n";
            } catch (...) { 
                std::cout << "🚨 [PopNextTask] JSON 파싱 에러\n";
                return BT::NodeStatus::FAILURE; 
            }
        }

        // 3. 큐에서 작업 하달
        if (task_queue_.empty()) {
            setOutput("action_name", std::string("none"));
            setOutput("target_name", std::string("none"));
            return BT::NodeStatus::RUNNING; 
        }

        Task next_task = task_queue_.front();
        task_queue_.pop();

        setOutput("action_name", next_task.action);
        setOutput("target_name", next_task.target);
        std::cout << "[PopNextTask] 🚀 다음 동작 하달 -> " << next_task.action << "\n";

        return BT::NodeStatus::SUCCESS;
    }

    void halt() override { 
        std::cout << "[PopNextTask] ⏸️ 노드 실행이 중단되었습니다.\n";
        setStatus(BT::NodeStatus::IDLE); 
    }
};