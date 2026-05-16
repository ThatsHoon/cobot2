from ..base_action import BaseAction

class Hello_bot(BaseAction):
    action_name = 'hello_bot'

    def execute(self):

        if not self.manager.perform('movej',joint=[0,10,120,-180,120,90], vel=150, acc=150, mode='abs'): return False

        # if not self.manager.perform('movej', joint=[0,0,0,0,0,], vel=100, acc=100, mode='abs'): return False
        if not self.manager.perform('periodic', amp=[0, 0, 0, 10, 0, 0], period=[0, 0, 0, 1, 0, 0], repeat=2): return False
        if not self.manager.perform('reset'): return False

        return True