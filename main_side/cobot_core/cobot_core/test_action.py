import json

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class TestVoiceCommand(Node):
    def __init__(self):
        super().__init__("test_voice_command")
        self.publisher = self.create_publisher(String, "/voice_command", 10)

    def publish_test_sequence(self):
        sequence = [
            {
                "action": "tap",
                "params": {'target':'toy_block'
                    },
                'decs' : '찍기'
            },
            {
                "action": "pick",
                "params": {'target':'apple'
                    },
                "desc": '잡기'
            },
            {
                "action": "trash",
                "params": {
                    },
                'decs' : '버리기'
            },
            {
                "action": "reset",
                "params": {},
                "desc": "reset",
            },
            {
                "action": "pick",
                "params": {'target':'shaker'
                    },
                "desc": '잡기'
            },
            {
                "action": "shake",
                "params": {
                    },
                "desc": '흔들기'
            },
            {
                "action": "reset",
                "params": {},
                "desc": "reset",
            }
        ]

        msg = String()
        msg.data = json.dumps(sequence, ensure_ascii=False)

        self.publisher.publish(msg)
        self.get_logger().info(
            f"📤 /voice_command 테스트 시퀀스 전송 완료: {len(sequence)} steps"
        )


def main(args=None):
    rclpy.init(args=args)

    node = TestVoiceCommand()

    try:
        # publisher/subscriber 매칭될 시간 살짝 대기
        for _ in range(5):
            rclpy.spin_once(node, timeout_sec=0.1)

        node.publish_test_sequence()

        # publish가 DDS로 나갈 시간 확보
        for _ in range(5):
            rclpy.spin_once(node, timeout_sec=0.1)

        node.get_logger().info("✅ action_tester 종료")

    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()