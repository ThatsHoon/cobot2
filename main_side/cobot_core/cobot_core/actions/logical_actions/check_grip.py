from ..base_action import BaseAction
import time

class CheckGrip(BaseAction):
    action_name = 'check_grip'

    def execute(self, target=None, **kwargs):
        logger = self.manager.node.get_logger()
        logger.info("🤖 그리퍼 파지 상태를 하드웨어 레벨에서 확인합니다...")
        
        try:
            # 1. OnRobot 그리퍼의 현재 상태와 폭(Width) 읽어오기
            status = self.manager.gripper.get_status()
            width = self.manager.gripper.get_width()
            
            logger.info(f"📊 그리퍼 스캔 결과 -> Status: {status}, Width: {width:.1f}mm")
            
            is_gripping = False

            # ----------------------------------------------------
            # 💡 경우 1: status가 딕셔너리(dict)로 파싱되어 나오는 경우
            # ----------------------------------------------------
            if isinstance(status, dict):
                # 'grip_detected' 같은 키가 있는지 확인
                is_gripping = status.get('grip_detected', False)
                
            # ----------------------------------------------------
            # 💡 경우 2: status가 원시 정수(int) 형태의 비트마스크인 경우
            # ----------------------------------------------------
            elif isinstance(status, int):
                # 2진수로 변환했을 때 'Grip Detected'를 의미하는 비트(보통 두 번째 비트) 확인
                # (10진수 2와 AND 연산을 하면 두 번째 비트가 1인지 알 수 있습니다)
                is_gripping = bool(status & 2) 

            # ----------------------------------------------------
            # 💡 경우 3: 만약 status 값을 도저히 모르겠다면? (최후의 보루)
            # ----------------------------------------------------
            # 완전히 닫히면 폭이 0.0 ~ 1.0mm 수준이므로, 2.0mm 이상이면 무언가 잡았다고 간주
            if not is_gripping and width > 2.0:
                logger.warn("⚠️ 상태 비트 확인 실패. 폭(Width) 데이터 기반 파지 판별로 대체합니다.")
                is_gripping = True

            # 최종 판별 결과
            if is_gripping:
                logger.info("✅ 물체 파지 확인 완료! 다음 동작을 허용합니다.")
                return True
            else:
                logger.error("❌ 물체가 없습니다 (허공). 동작을 중단(Abort)합니다.")
                # 💡 옵션: 그리퍼를 다시 활짝 열어주는 센스!
                self.manager.perform('gripper_open')
                return False

        except Exception as e:
            logger.error(f"⚠️ 그리퍼 상태 확인 중 에러 발생: {e}")
            # 통신 에러 시 안전을 위해 중단
            return False