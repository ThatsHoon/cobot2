import rclpy
import json
import time
from rclpy.node import Node
from std_msgs.msg import String

# 💡 팀원 로직에 맞춘 시스템 메시지 임포트
from dsr_msgs2.srv import MoveStop, DrlStop, SetSafetyMode, SetRobotControl, SetRobotMode

class StateManager(Node):
    def __init__(self):
        super().__init__('state_manager')
        
        self.create_subscription(String, '/admin_command', self.admin_cmd_cb, 10)
        
        # 💡 하드웨어 3단 정지 클라이언트
        self.stop_cli = self.create_client(MoveStop, '/dsr01/motion/move_stop')
        self.drl_stop_cli = self.create_client(DrlStop, '/dsr01/drl/drl_stop')
        self.safety_mode_cli = self.create_client(SetSafetyMode, '/dsr01/system/set_safety_mode')
        
        # 💡 복구용 클라이언트
        self.control_cli = self.create_client(SetRobotControl, '/dsr01/system/set_robot_control')
        self.mode_cli = self.create_client(SetRobotMode, '/dsr01/system/set_robot_mode')
        
        self.get_logger().info("🛡️ State Manager Ready")

    def admin_cmd_cb(self, msg):
        try:
            data = json.loads(msg.data)
            cmd = data.get("command", "").upper()
            
            if cmd == "ESTOP":
                self.get_logger().fatal("🛑 [ADMIN] E-STOP! 하드웨어 RECOVERY 모드 진입!")
                self.trigger_estop()
                
            elif cmd == "UNLOCK":
                self.get_logger().info("🔓 [ADMIN] UNLOCK! RECOVERY 해제 및 제어권 반환!")
                self.trigger_unlock()
                
        except Exception as e:
            self.get_logger().warn(f"관리자 명령 파싱 실패: {e}")

    def _track(self, future, label):
        """call_async 결과를 비블로킹으로 추적 — 정지 명령 실패 가시화.
        (응답 없으면 비상정지가 silent 실패하므로 안전상 필수)"""
        def _done(fut):
            try:
                fut.result()
                self.get_logger().info(f"✅ [하드웨어] {label} 응답 수신")
            except Exception as e:
                self.get_logger().error(f"❌ [하드웨어] {label} 실패: {e}")
        future.add_done_callback(_done)

    def trigger_estop(self):
        # 1. 현재 모션 즉각 정지 (stop_mode=1)
        if self.stop_cli.wait_for_service(timeout_sec=1.0):
            req_stop = MoveStop.Request()
            req_stop.stop_mode = 1
            self._track(self.stop_cli.call_async(req_stop), "move_stop")
        else:
            self.get_logger().error("❌ [하드웨어] move_stop 서비스 미응답 — 정지 불확실!")

        # 2. DRL 스크립트 정지 (stop_mode=1)
        if self.drl_stop_cli.wait_for_service(timeout_sec=1.0):
            req_drl = DrlStop.Request()
            req_drl.stop_mode = 1
            self._track(self.drl_stop_cli.call_async(req_drl), "drl_stop")
        else:
            self.get_logger().error("❌ [하드웨어] drl_stop 서비스 미응답!")

        # 3. 하드웨어 RECOVERY 모드 강제 전환 (명령 완전 차단)
        if self.safety_mode_cli.wait_for_service(timeout_sec=1.0):
            req_safety = SetSafetyMode.Request()
            req_safety.safety_mode = 2  # RECOVERY
            req_safety.safety_event = 0 # ENTER
            self._track(self.safety_mode_cli.call_async(req_safety), "safety_mode=RECOVERY")
            self.get_logger().fatal("🛑 [하드웨어] RECOVERY 방화벽 작동 요청 전송!")
        else:
            self.get_logger().error("❌ [하드웨어] set_safety_mode 서비스 미응답!")

    def trigger_unlock(self):
        # 1. RECOVERY 모드 탈출 (robot_control=7)
        if self.control_cli.wait_for_service(timeout_sec=1.0):
            req_reset = SetRobotControl.Request()
            req_reset.robot_control = 7 # CONTROL_RESET_RECOVERY
            self._track(self.control_cli.call_async(req_reset), "reset_recovery")

        time.sleep(0.5)

        # 2. 자율 모드로 복귀 (명령 수신 재개)
        if self.mode_cli.wait_for_service(timeout_sec=1.0):
            req_mode = SetRobotMode.Request()
            req_mode.robot_mode = 1
            self._track(self.mode_cli.call_async(req_mode), "robot_mode=AUTONOMOUS")
            self.get_logger().info("✅ [하드웨어] 스탠바이 복귀 요청 전송!")

def main(args=None):
    rclpy.init(args=args)
    node = StateManager()
    try: 
        rclpy.spin(node)
    except KeyboardInterrupt: 
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()