#include <behaviortree_cpp_v3/condition_node.h>
#include <string>

class IsResetAction : public BT::ConditionNode {
public:
    IsResetAction(const std::string& name, const BT::NodeConfiguration& config)
        : BT::ConditionNode(name, config) {}

    static BT::PortsList providedPorts() {
        return { BT::InputPort<std::string>("action_name") };
    }

    BT::NodeStatus tick() override {
        std::string action;
        if (getInput<std::string>("action_name", action) && action == "reset") {
            return BT::NodeStatus::SUCCESS;
        }
        return BT::NodeStatus::FAILURE;
    }
};