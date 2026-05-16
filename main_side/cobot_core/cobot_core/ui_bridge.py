import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
import json
import time
from std_msgs.msg import String
from rcl_interfaces.msg import Log

class UIBridgeNode(Node):
    def __init__(self):
        super().__init__('ui_bridge_node')
        
        # [설정 스위치]
        self.TEST_MODE = True

        # 상태 log
        self.system_state = {
            "status":        "",
            "stt_result":    "",
            "voice_command": "",
            "detection":     "",
            "rosout":        "",
            "last_update":   ""
        }

        self.get_logger().info(f"🌉 UI Bridge 가동 (테스트 모드: {self.TEST_MODE})")

        rosout_qos = QoSProfile(
            depth=100,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )

        # 정보 통합 (Input)
        self.create_subscription(Log, '/rosout', self.rosout_cb, rosout_qos)
        self.create_subscription(String, '/stt_result', self.stt_cb, 10)
        self.create_subscription(String, '/voice_command', self.cmd_cb, 10)
        self.create_subscription(String, '/status', self.status_cb, 10)
        self.create_subscription(String, '/detection', self.detection_cb, 10)

        self.pub_ui_state = self.create_publisher(String, '/ui_bridge/state', 10)

        # 통합 전송 타이머 (10Hz)
        self.timer = self.create_timer(0.1, self.publish_combined_state)

    _LOG_LEVEL = {10: 'DEBUG', 20: 'INFO', 30: 'WARN', 40: 'ERROR', 50: 'FATAL'}

    def rosout_cb(self, msg: Log):
        self.system_state["rosout"] = json.dumps({
            "level": self._LOG_LEVEL.get(msg.level, str(msg.level)),
            "node":  msg.name,
            "msg":   msg.msg,
        }, ensure_ascii=False)

    def stt_cb(self, msg):
        self.system_state["stt_result"] = msg.data

    def cmd_cb(self, msg):
        self.system_state["voice_command"] = msg.data

    def status_cb(self, msg):
        self.system_state["status"] = msg.data

    def detection_cb(self, msg):
        self.system_state["detection"] = msg.data

    def publish_combined_state(self):
        self.system_state["last_update"] = time.strftime('%Y-%m-%d %H:%M:%S')
        msg = String()
        msg.data = json.dumps(self.system_state, ensure_ascii=False)
        self.pub_ui_state.publish(msg)

def main(args=None):
    rclpy.init(args=args)
    node = UIBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()