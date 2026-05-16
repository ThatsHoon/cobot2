from ..base_action import BaseAction


class ApproachAction(BaseAction):
    """BT 변칙 대응 단계 — 타겟 가시성 최종 확인(locate).

    정밀 접근·파지 모션은 grasp_perception_node(동적 pick)가 전담하므로,
    여기서는 로봇을 움직이지 않고 locate 로 타겟을 재확인하고
    target_pos 를 갱신한다. (모션 소유권 분리: 충돌 방지 contract)
    """
    action_name = 'approach'

    def execute(self, target, **kwargs):
        logger = self.manager.node.get_logger()
        if not target or target == 'none':
            logger.error("🎯 타겟이 지정되지 않았습니다.")
            return False

        logger.info(f"🚁 '{target}' 가시성 확인(locate)")
        pos = self.manager.get_vision_target(target)
        if pos:
            logger.info("✅ 타겟 확인 완료 — 동적 pick 으로 진행 가능")
            return True
        logger.error("❌ 타겟 확인 실패!")
        return False
