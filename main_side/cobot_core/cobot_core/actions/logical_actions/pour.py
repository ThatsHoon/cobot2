from ..base_action import BaseAction
import time

class Pour(BaseAction):
    """용기를 자연스럽게 기울여 내용물을 붓고 제자리로 돌아오는 동작"""
    action_name = 'pour'

    def execute(self, target=None, **kwargs):  
        current_joint = self.get_current_posj()
        if 85 <= current_joint[2] <= 95 and 85 <= current_joint[4] <= 95 :
            vertical_current_pos = self.get_current_posx()
            current_rx, current_ry, current_rz = vertical_current_pos[3], vertical_current_pos[4], vertical_current_pos[5]
            if not self.manager.perform('movel', pos=[312,-198,187,current_rx,current_ry,current_rz],vel=100,acc=100,mode='abs'): return False
            if not self.manager.perform('movej', joint=[0,0,0,0,0,90], vel=50, acc=50, mode='rel'): return False      
            if not self.manager.perform('movel', pos=[0,0,0,0,35,90], vel=50, acc=50, mode='rel', ref='tool'): return False
            self.wait(time=3)
            if not self.manager.perform('movej', joint=[0,0,90,0,90,0], vel=100, acc=100, mode='abs'): return False
        # 붓는 위치로 이동
        else:
            horizontal_current_pos = self.get_current_posx()
            horizontal_current_rx, horizontal_current_ry, horizontal_current_rz = horizontal_current_pos[3], horizontal_current_pos[4],horizontal_current_pos[5]
            if not self.manager.perform('movel', pos=[312,-198,187,horizontal_current_rx,horizontal_current_ry,horizontal_current_rz],vel=100,acc=100): return False
            if not self.manager.perform('movej',joint=[0,0,0,0,0,90],vel=100,acc=100,mode='rel'): return False
            self.wait(time=3)
            if not self.manager.perform('movej',joint=[0,0,0,0,0,-90],vel=100,acc=100,mode='rel'): return False