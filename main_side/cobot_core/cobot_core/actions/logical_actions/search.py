from ..base_action import BaseAction

class Search(BaseAction):
    action_name = 'search'

    def execute(self, target=None, **kwargs):
        if not target: return False
        
        logger = self.manager.node.get_logger()
        logger.info(f"🔎 '{target}' 능동 스캔(Search) 시작...")

        # 스캔 패턴: 좌측 30도 -> 우측 60도(원점 기준 우측 30도) -> 원위치 복귀
        scan_angles = [30, -60, 30] 
        
        self.manager.perform('reset')
         
        for angle in scan_angles:
            # Base(J1) 관절을 상대 각도로 회전
            if not self.manager.perform('movej', joint=[angle, 0, 0, 0, 0, 0], vel=100, acc=100, mode='rel'): 
                return False
            
            self.wait(0.5) # 카메라 안정화
            
            # 카메라에 타겟이 잡히면 즉시 스캔 성공!
            if self.manager.get_vision_target(target):
                logger.info(f"✅ '{target}' 발견! 스캔을 종료합니다.")
                return True

        logger.warn(f"❌ 주변을 모두 스캔했지만 '{target}'을 찾을 수 없습니다.")
        return False