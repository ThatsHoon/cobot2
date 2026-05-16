from ..base_action import BaseAction
import time

class Finding(BaseAction):
    action_name = 'finding'

    def execute(self, target=None, max_try=3, x_step=150, wait_time=0.5, **kwargs):
        if not target:
            print("❌ [finding] target 이름이 없습니다.")
            return False

        print(f"🔍 [finding] '{target}' 탐색 시작")

        if not self.manager.perform('movel', pos = ([-100,0,0,0,0,0]), vel=200, acc=200, mode='rel'): return False

        for i in range(max_try):
            print(f"🔎 [finding] 탐색 루프 {i + 1}/{max_try}")

            # 1. 현재 위치에서 탐색
            if self.manager.get_vision_target(target) is not None: return True

            # 2. J6 +180 회전
            if not self.manager.perform('movej',joint=[0, 0, 0, 0, 0, 180],vel=200,acc=200,mode='rel'): return False

            # 3. 회전 후 탐색
            if self.manager.get_vision_target(target) is not None: return True

            # 4. J6 -180 원복
            if not self.manager.perform('movej',joint=[0, 0, 0, 0, 0, -180],vel=200,acc=200,mode='rel'): return False

            # 5. X +100 이동
            if not self.manager.perform('movel',pos=[x_step, 0, 0, 0, 0, 0],vel=200,acc=200,mode='rel'): return False

        print(f"❌ [finding] '{target}' 탐색 실패")
        return False

    # def _check_target(self, target):
    #     pos = self.manager.get_vision_target(target)
    #     print(f"🧪 [finding] get_vision_target 반환값: {pos}, type={type(pos)}")

    #     if pos is not None:
    #         print(f"👀 [finding] 타겟 후보 발견: {target}, 좌표 계산 대기 중...")

    #         # 5초 뒤 좌표 다시 읽기
    #         pos = self.manager.get_vision_target(target)

    #         if not pos:
    #             print(f"❌ [finding] 5초 뒤 타겟 좌표가 사라짐: {target}")
    #             return False

    #         print(f"✅ [finding] 타겟 확정: {target}, pos={pos}")

    #         # # 다음 액션에서 쓰게 저장
    #         self.manager.target = target
    #         self.manager.target_pos = pos

    #         return True

    #     print(f"👀 [finding] 아직 안 보임: {target}")
    #     return False