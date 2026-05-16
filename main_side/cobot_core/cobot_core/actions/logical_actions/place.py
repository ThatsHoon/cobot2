from ..base_action import BaseAction

class Place(BaseAction):
    action_name = 'place'

    def execute(self, target=None, **kwargs):
        if not target:
            print("❌ 타겟이 지정되지 않았습니다.")
            return False
        
        if target == 'right_box':
            if not self.manager.perform('movej', joint=[-79,13,78,0,88,-78], mode='abs', acc= 100, vel=100): return False
        elif target == 'left_box':
            if not self.manager.perform('movej', joint=[-39,47,25,0,108,-38], mode='abs', acc= 100, vel=100): return False

        if not self.manager.perform('gripper_open'): return False

        if not self.manager.perform('movel', pos=[0,0,-100,0,0,0], mode='rel', ref='tool'): return False

        return True