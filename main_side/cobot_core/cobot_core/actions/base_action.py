from cobot_core.controller.dsr_controller import DSRobotController

class BaseAction(DSRobotController):
    action_name = None 
    
    def __init__(self, manager):
        super().__init__(manager) # DSRRobotController에게 manager 넘겨줌
    
    @property
    def depth_offset(self):
        return self.manager.node.depth_offset
    
    @property
    def tilt_angle(self):
        return self.manager.node.tilt_angle
    

    def execute(self, **kwargs):
        raise NotImplementedError
    
    
    def reset(self, **kwargs):
        from DSR_ROBOT2 import movej
        from DSR_ROBOT2 import posj
        
        res = movej(posj(0, 0, 90, 0, 90, 0), vel=self.vel_angular, acc=self.acc_angular)
        
        if res != 0:
            print(f"⚠️ 예외사항 발생!: {res}")
            return False
        self.gripper_open()
        return True
    
    def clear_alarm(self, **kwargs):
        """ROS 2 순수 서비스 호출로 에러 복구 (PyDSR 제너레이터 충돌 방지)"""
        import DR_init
        from dsr_msgs2.srv import SetRobotControl
        import time

        node = getattr(DR_init, '__dsr__node')
        ns = node.get_namespace()
        if ns == "/": ns = "/dsr01"
        
        cli = node.create_client(SetRobotControl, f'{ns}/system/set_robot_control')
        
        if not cli.wait_for_service(timeout_sec=2.0):
            print(f"⚠️ {ns}/system/set_robot_control 서비스 찾기 실패.")
            return False

        # 에러 리셋(2) 비동기 전송
        req = SetRobotControl.Request()
        req.robot_control = 2
        cli.call_async(req)
        
        print("⏳ 안전 리셋(2) 서비스 호출 완료. BT 트리에 제어권을 반환합니다.")
        time.sleep(1.0) # 하드웨어 반영을 위한 짧은 대기
        return True