"""db_logger — ROS → MySQL 영속화 릴레이 (main_side 네이티브 노드).

목적: 디버깅용 admin 웹(robot 컨테이너)이 DDS 그래프에 직접 참여하지
못하는 문제(컨테이너 RMW/SHM 격리·cross-host 디스커버리)를 우회한다.
이 노드는 호스트의 정상 DDS 그래프에서 토픽을 구독해 MySQL 에 직접
기록하므로, robot 컨테이너는 ROS 없이 DB 만 read 하면 된다.

구독:
  /voice_command (std_msgs/String, JSON 배열)  → command_logs 생성 + detail
  /stt_result    (std_msgs/String)             → raw_text 캐시
  /status        (std_msgs/String, {state,action,target}) → 상태 생명주기
  /rosout        (rcl_interfaces/Log)           → error_logs (WARN/ERROR/FATAL)

DB I/O 는 백그라운드 워커 스레드 + 큐로 분리한다. rclpy 콜백은 절대
DB 접속/재접속에 블로킹되지 않으며, DB 장애 시에도 ROS 측은 무영향.

command_id 생명주기(휴리스틱 — bt_manager 의 KeepRunningUntilFailure 는
전체 시퀀스 SUCCESS 를 내지 않고 idle 도 FAILURE 로 표기하므로):
  /voice_command 수신       → 신규 command_id, status='received'
  /status RUNNING & action≠none → 'executing' (최초 시 started_at)
  executing 이후 FAILURE     → 에러 있었으면 'failed' 아니면 'done', finished_at
  /status PAUSED            → 'paused'
"""
import json
import os
import queue
import threading
import time
import uuid
from datetime import datetime

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from std_msgs.msg import String
from rcl_interfaces.msg import Log

_LEVEL = {10: "DEBUG", 20: "INFO", 30: "WARN", 40: "ERROR", 50: "FATAL"}
_PERSIST_LEVELS = {"WARN", "ERROR", "FATAL"}


class DBLogger(Node):
    def __init__(self):
        super().__init__("db_logger")

        self._last_stt = ""
        # 활성 명령: {"id", "started"(bool), "executing"(bool), "errors"(int)}
        self._active = None
        self._lock = threading.Lock()

        # DB 쓰기 작업 큐 + 워커 스레드 (rclpy 콜백 비차단)
        self._q: "queue.Queue[tuple]" = queue.Queue(maxsize=2000)
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._db_worker, daemon=True)
        self._worker.start()

        self.create_subscription(String, "/voice_command", self._on_voice_command, 10)
        self.create_subscription(String, "/stt_result", self._on_stt, 10)
        self.create_subscription(String, "/status", self._on_status, 10)
        # /rosout 은 ui_bridge 와 동일 QoS (지연 가입 시 과거 로그 확보)
        rosout_qos = QoSProfile(depth=100,
                                reliability=ReliabilityPolicy.RELIABLE,
                                durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(Log, "/rosout", self._on_rosout, rosout_qos)

        self.get_logger().info("🗄️ db_logger 가동 — ROS→MySQL 릴레이 (컨테이너는 DB-only)")

    # ── ROS 콜백 (큐에 적재만, 비차단) ──────────────────────────
    def _on_stt(self, msg):
        self._last_stt = msg.data or ""

    def _on_voice_command(self, msg):
        try:
            seq = json.loads(msg.data) if msg.data else []
        except (json.JSONDecodeError, TypeError):
            seq = []
        cmd_id = "cmd-" + datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        detail = json.dumps({"raw_text": self._last_stt, "sequence": seq},
                            ensure_ascii=False)
        with self._lock:
            # 직전 명령이 아직 열려있으면(다중 명령) 먼저 종결 처리 —
            # 안 하면 1번 명령이 영구 'executing' 으로 DB 에 고착.
            prev = self._active
            if prev is not None:
                final = "failed" if prev["errors"] > 0 else "done"
                self._enqueue(("finish", {"command_id": prev["id"], "status": final}))
            self._active = {"id": cmd_id, "started": False,
                            "executing": False, "errors": 0}
        self._enqueue(("create", {
            "command_id": cmd_id,
            "raw_text": self._last_stt,
            "status": "received",
            "action_count": len(seq) if isinstance(seq, list) else 0,
            "detail": detail,
        }))

    def _on_status(self, msg):
        try:
            st = json.loads(msg.data)
        except (json.JSONDecodeError, TypeError):
            return
        state = st.get("state", "")
        action = st.get("action", "none")
        with self._lock:
            act = self._active
            if act is None:
                return
            if state == "RUNNING" and action and action != "none":
                if not act["started"]:
                    act["started"] = True
                    act["executing"] = True
                    self._enqueue(("status", {
                        "command_id": act["id"], "status": "executing",
                        "current_action": action, "started": True}))
                else:
                    self._enqueue(("status", {
                        "command_id": act["id"], "status": "executing",
                        "current_action": action, "started": False}))
            elif state == "PAUSED":
                self._enqueue(("status", {
                    "command_id": act["id"], "status": "paused",
                    "current_action": action, "started": False}))
            elif state == "FAILURE" and act["executing"]:
                # KeepRunningUntilFailure: 시퀀스 종료(큐 비움)도 FAILURE.
                # 에러 발생 여부로 done/failed 구분.
                final = "failed" if act["errors"] > 0 else "done"
                self._enqueue(("finish", {
                    "command_id": act["id"], "status": final}))
                self._active = None

    def _on_rosout(self, msg: Log):
        level = _LEVEL.get(msg.level, str(msg.level))
        if level not in _PERSIST_LEVELS:
            return
        with self._lock:
            cmd_id = self._active["id"] if self._active else None
            if self._active is not None:
                self._active["errors"] += 1
        self._enqueue(("error", {
            "command_id": cmd_id, "level": level,
            "node_name": msg.name or "", "message": msg.msg or ""}))

    def _enqueue(self, item):
        try:
            self._q.put_nowait(item)
        except queue.Full:
            self.get_logger().warn("db_logger 큐 가득참 — 항목 드롭 (DB 지연?)")

    # ── DB 워커 스레드 ─────────────────────────────────────────
    def _db_worker(self):
        conn = None
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=1.0)
            except queue.Empty:
                continue
            for attempt in range(2):  # 1회 재접속 재시도
                try:
                    if conn is None:
                        conn = self._connect()
                    self._write(conn, item)
                    break
                except Exception as e:
                    self.get_logger().warn(f"DB write 실패({attempt}): {e}")
                    try:
                        if conn:
                            conn.close()
                    except Exception:
                        pass
                    conn = None
                    time.sleep(1.0)
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    def _connect(self):
        import pymysql
        conn = pymysql.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "3306")),
            user=os.getenv("DB_USER", "robot"),
            password=os.getenv("DB_PASSWORD", ""),
            database=os.getenv("DB_NAME", "robot_admin"),
            charset="utf8mb4", autocommit=True, connect_timeout=5)
        self.get_logger().info("✅ MySQL 연결 성공 (db_logger)")
        return conn

    def _write(self, conn, item):
        kind, d = item
        with conn.cursor() as cur:
            if kind == "create":
                cur.execute(
                    "INSERT INTO command_logs "
                    "(command_id, raw_text, status, action_count, detail) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (d["command_id"], d["raw_text"], d["status"],
                     d["action_count"], d["detail"]))
            elif kind == "status":
                if d["started"]:
                    cur.execute(
                        "UPDATE command_logs SET status=%s, current_action=%s, "
                        "started_at=COALESCE(started_at, NOW()) WHERE command_id=%s",
                        (d["status"], d["current_action"], d["command_id"]))
                else:
                    cur.execute(
                        "UPDATE command_logs SET status=%s, current_action=%s "
                        "WHERE command_id=%s",
                        (d["status"], d["current_action"], d["command_id"]))
            elif kind == "finish":
                cur.execute(
                    "UPDATE command_logs SET status=%s, finished_at=NOW() "
                    "WHERE command_id=%s",
                    (d["status"], d["command_id"]))
            elif kind == "error":
                cur.execute(
                    "INSERT INTO error_logs "
                    "(command_id, level, node_name, message) VALUES (%s,%s,%s,%s)",
                    (d["command_id"], d["level"], d["node_name"], d["message"]))
                if d["command_id"]:
                    cur.execute(
                        "UPDATE command_logs SET error_count=error_count+1 "
                        "WHERE command_id=%s", (d["command_id"],))

    def destroy_node(self):
        self._stop.set()
        if self._worker.is_alive():
            self._worker.join(timeout=3.0)
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = DBLogger()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
