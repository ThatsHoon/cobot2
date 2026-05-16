from ..base_action import BaseAction

class Tap(BaseAction):
    action_name = 'tap'

    def execute(self, target=None, **kwargs):
        pos = self.manager.get_vision_target(target)

        if not pos:
            if not self.manager.perform('finding', target=target):
                print(f"❌ '{target}' finding 실패")
                return False

            pos = self.manager.target_pos

            if not pos:
                print(f"❌ '{target}' finding 후에도 좌표가 없습니다.")
                return False

        tx, ty, tz, rx, ry, rz = pos
        if not self.manager.perform('gripper_close'): return False
        if not self.manager.perform('movel', pos=[tx, ty, tz+100, rx, ry, rz], vel=100, acc=100, mode='abs'): return False
        if not self.manager.perform('periodic', amp=[0, 0, 5, 0, 0, 0], period=[0, 0, 0.5, 0, 0, 0], repeat=2): return False
        return True