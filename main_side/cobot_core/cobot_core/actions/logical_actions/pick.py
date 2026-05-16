from ..base_action import BaseAction


class Pick(BaseAction):
    """동적 pick — 분석 기반 자동대응 파지.

    실제 인지(YOLO→VLM→포인트클라우드 구조 분석)와 그리퍼 자동대응
    접근·파지 모션은 grasp_perception_node 가 전담한다. 이 액션은
    /grasp_object(mode="grasp") 를 호출하는 얇은 클라이언트일 뿐이다.
    (객체별 잡는 방식 고정 로직 제거 — 구조 해석으로 자동 결정)
    """
    action_name = 'pick'

    def execute(self, target=None, **kwargs):
        logger = self.manager.node.get_logger()
        if not target or target == 'none':
            logger.error("🦾 타겟이 지정되지 않았습니다.")
            return False
        logger.info(f"🦾 '{target}' 동적 pick 시작 (grasp_perception_node 위임)")
        return self.manager.request_grasp(target)
