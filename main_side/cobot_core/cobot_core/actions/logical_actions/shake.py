from ..base_action import BaseAction

class Shake(BaseAction):
    action_name = 'shake'

    def execute(self, amp=[0, 0, 40, 0, 0, 0], period=[0, 0, 0.5, 0, 0, 0], repeat=5, target=None, **kwargs):
        """진폭값(amp=list[6]), 주기(period=list[6]), 반복회수(repeat=int)"""
        if not self.manager.perform('periodic', 
                                     amp=amp, 
                                     period=period, 
                                     repeat=repeat): 
                                     return False