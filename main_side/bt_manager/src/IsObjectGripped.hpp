#include <behaviortree_cpp_v3/condition_node.h>
#include <iostream>

class IsObjectGripped : public BT::ConditionNode {
public:
    IsObjectGripped(const std::string& name, const BT::NodeConfiguration& config)
        : BT::ConditionNode(name, config) {}

    static BT::PortsList providedPorts() {
        return {}; // 입력받을 포트 없음
    }

    BT::NodeStatus tick() override {
        std::cout << "[IsObjectGripped] 🤖 그리퍼 파지 상태 확인 중...\n";

        // TODO: 컨트롤러의 현재 상태 또는 그리퍼의 Modbus TCP 피드백(Width, Force 등)을 읽어와서 파지 여부 검사
        
        // (테스트용) 아직 아무것도 안 잡고 있다고 가정
        bool is_gripped = false; 

        if (is_gripped) {
            std::cout << "  -> ✅ 물체를 안전하게 쥐고 있습니다.\n";
            return BT::NodeStatus::SUCCESS;
        } else {
            std::cout << "  -> ❌ 허공을 쥐고 있습니다! 동작 중단.\n";
            return BT::NodeStatus::FAILURE;
        }
    }
};