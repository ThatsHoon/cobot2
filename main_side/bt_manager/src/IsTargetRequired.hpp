#include <behaviortree_cpp_v3/condition_node.h>
#include <string>

class IsTargetRequired : public BT::ConditionNode {
public:
    IsTargetRequired(const std::string& name, const BT::NodeConfiguration& config)
        : BT::ConditionNode(name, config) {}

    static BT::PortsList providedPorts() {
        return { BT::InputPort<std::string>("target_name") };
    }

    BT::NodeStatus tick() override {
        std::string target;
        
        // 1. 포트에서 target_name을 아예 못 읽어오거나
        // 2. 값이 비어있거나("")
        // 3. 값이 "none"으로 설정되어 있다면 -> 타겟이 필요 없는 동작으로 간주!
        if (!getInput<std::string>("target_name", target) || target.empty() || target == "none") {
            // FAILURE를 반환하면 Groot의 Fallback이 오른쪽(SequenceWithoutTarget)으로 넘어갑니다.
            return BT::NodeStatus::FAILURE; 
        }

        // 그 외의 동작(pick, place, search 등)은 타겟이 필요하므로 SUCCESS 반환
        return BT::NodeStatus::SUCCESS; 
    }
};