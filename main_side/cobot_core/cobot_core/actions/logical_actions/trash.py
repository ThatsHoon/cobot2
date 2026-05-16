from ..base_action import BaseAction

class Trash(BaseAction):
    action_name = 'trash'

    def execute(self, target=None, **kwargs):
        if not self.manager.perform('movej', 
                                    joint=[0,0,90,0,90,0], 
                                    mode='abs', 
                                    acc= 100, 
                                    vel=100):  return False
        if not self.manager.perform('movej', 
                                    joint=[180,0,0,0,0,0], 
                                    mode='rel', 
                                    acc= 50, 
                                    vel=50): 
                                    return False
        if not self.manager.perform('gripper_open'): return False

        return True