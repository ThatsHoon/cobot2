#include <behaviortree_cpp_v3/condition_node.h>
#include <string>
#include <iostream>

class IsTargetLocated : public BT::ConditionNode {
public:
    IsTargetLocated(const std::string& name, const BT::NodeConfiguration& config)
        : BT::ConditionNode(name, config) {}

    static BT::PortsList providedPorts() {
        return { BT::InputPort<std::string>("target_name") };
    }

    BT::NodeStatus tick() override {
        std::string target;
        if (!getInput<std::string>("target_name", target)) {
            return BT::NodeStatus::FAILURE;
        }

        std::cout << "[IsTargetLocated] 📡 '" << target << "'의 좌표 데이터 존재 여부 확인 중...\n";

        // TODO: 실제 텔레메트리 SQL 데이터베이스(또는 Redis/Topic)에서 최신 좌표 조회 로직
        // 예: SELECT x, y, z FROM vision_telemetry WHERE object_id = target ORDER BY timestamp DESC LIMIT 1;
        
        bool has_coordinates = false; // 기본적으로 아직 못 찾았다고 가정 (SearchTarget을 유도하기 위함)

        // (테스트용) 사과는 이미 좌표를 알고 있다고 가정
        // if (target == "apple") {
        //     has_coordinates = true;
        // }

        if (has_coordinates) {
            std::cout << "  -> ✅ 좌표 확인 완료! SearchTarget 스킵.\n";
            return BT::NodeStatus::SUCCESS;
        } else {
            std::cout << "  -> ❌ 좌표 없음! SearchTarget 실행 필요.\n";
            return BT::NodeStatus::FAILURE;
        }
    }
};