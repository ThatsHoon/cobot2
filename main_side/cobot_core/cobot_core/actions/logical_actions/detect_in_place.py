from ..base_action import BaseAction

class DetectInPlace(BaseAction):
    action_name = 'detect_in_place'

    def execute(self, target=None, **kwargs):
        logger = self.manager.node.get_logger()
        logger.info(f"🔎 제자리에서 '{target}' 탐지를 시도합니다...")

        if not target or target == 'none':
            return False

        # get_vision_target은 성공 시 ActionManager 메모리에 좌표를 자동 저장합니다!
        pos = self.manager.get_vision_target(target)
        
        if pos:
            logger.info(f"✅ 제자리 탐지 성공! (좌표 저장 완료)")
            return True
        else:
            logger.warn(f"❌ 제자리 탐지 실패. 능동 탐색(finding)으로 넘어갑니다.")
            return False