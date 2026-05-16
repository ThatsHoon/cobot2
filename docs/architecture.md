# cobot2 아키텍처 — 노드 & 기능 정리

> 웹 음성(STT/TTS)으로 들어온 명령이 로봇 동작까지 흘러가는 전체 파이프라인.
> 경로 참조 문제는 무시하고, **각 노드가 무슨 일을 하는지**만 심플하게 정리한 문서.

---

## 1. 전체 흐름 한눈에

```
[웹 프론트]  사용자 음성
    │  (브라우저 마이크 / 깨우기 단어)
    ▼
[음성 처리]  wakeup → STT(Whisper) → LLM(GPT) 명령 파싱
    │  → /voice_command (액션 시퀀스 JSON)
    │  → /voice_reply  (사람한테 들려줄 답변 텍스트 → TTS)
    ▼
[BT 매니저]  시퀀스를 큐로 쪼개 한 스텝씩 디스패치
    │  → execute_command (ROS2 Action)
    ▼
[Executer]   스텝마다 ActionManager.perform(action)
    │
    ├─▶ [Object Detection] /get_3d_position 으로 대상 3D 좌표 요청
    │
    └─▶ [Logical Action] DSR 로봇 모션 + 그리퍼 제어
            (pick / place / pour / shake … 25종)
    ▼
   Doosan m0609 로봇 + OnRobot 그리퍼 실제 동작
```

병렬로 `state_manager`(비상정지), `ui_bridge`(상태 집계)가 항상 떠 있다.

---

## 2. 폴더 구조 요약

| 영역 | 내용 |
|---|---|
| `main_side/` | 로봇이 도는 메인 PC 측 ROS2 패키지 (음성·BT·코어·비전·인터페이스) |
| `sub1_side/web/` | 브라우저 UI + FastAPI 백엔드 (음성 입출력, TTS) |
| `common/` | 공용 유틸(rokey jog/pose 툴), YOLO 학습 시퀀스 |

---

## 3. 노드별 기능 (핵심)

### 3-1. 웹 / 음성 입구 (`sub1_side/web`, `main_side/voice_processing`)

| 노드 / 프로세스 | 위치 | 한 줄 책임 | 주요 토픽·엔드포인트 |
|---|---|---|---|
| `client_bridge_node` | web/backend/main.py | ROS2 토픽 ↔ 브라우저 WebSocket 브리지 + OpenAI TTS 프록시 | sub: `/wakeup_status` `/stt_result` `/voice_reply` · HTTP `GET /tts` · WS `/ws/client` |
| `wakeup_worker_node` | web/backend/wakeup_worker.py | 깨우기 단어 감지 → 5초 녹음 → Whisper STT → GPT 명령 파싱 (웹 연동판) | pub: `/wakeup_status` `/stt_result` `/voice_command` `/voice_reply` |
| `voice_to_command` | voice_processing/voice_to_command.py | wakeup_worker 와 동일 역할의 헤드리스(런치) 버전 | sub: `/status` · pub: 위와 동일 4종 |
| `voice_client` | voice_processing/voice_client.py | `/voice_reply` 받아 터미널에서 TTS 재생(mpg123) | sub: `/voice_command` `/voice_reply` |
| 프론트엔드 | web/frontend/index.html | Rive 캐릭터 UI, STT 자막 표시, `/tts` 호출해 음성 재생 | WS 수신만 |

> 음성 파이프라인은 **두 갈래**(웹용 wakeup_worker / 헤드리스 voice_to_command)가 같은 `/voice_command`·`/voice_reply` 토픽으로 합류한다.
> 공용 부품: `stt.py`(Whisper), `wakeup_word.py`(openwakeword), `MicController.py`(마이크), `prompt.py`(LLM 프롬프트·액션 카탈로그).

### 3-2. 작업 오케스트레이션 (`main_side/bt_manager`, `main_side/cobot_core`)

| 노드 | 위치 | 한 줄 책임 | 주요 인터페이스 |
|---|---|---|---|
| `bt_manager` (C++) | bt_manager/src/main.cpp | `/voice_command` JSON 을 큐로 쪼개 BT 틱(10Hz)으로 한 스텝씩 실행, E-STOP 시 큐 비움 | sub: `/voice_command` `/admin_command` · **Action Client**: `execute_command` |
| `command_executer` | cobot_core/controller/executer.py | `execute_command` 액션 서버 — 시퀀스 스텝마다 `ActionManager.perform()` 호출, 피드백/결과 반환 | **Action Server**: `execute_command` (command/Command) |
| `state_manager` | cobot_core/state_manager.py | `/admin_command` 의 ESTOP/UNLOCK 처리 — 3단계 하드웨어 정지 & 복구 | sub: `/admin_command` · DSR 안전 서비스 호출 |
| `ui_bridge_node` | cobot_core/ui_bridge.py | 로그·STT·명령·상태·검출을 한 JSON 으로 모아 10Hz 발행 | sub: `/rosout` `/stt_result` `/voice_command` `/status` `/detection` · pub: `/ui_bridge/state` |

**BT 노드(조건/액션):** `PopNextTask`(큐 pop), `IsTargetRequired`/`IsTargetLocated`/`IsObjectGripped`/`IsResetAction`(조건), `ExecutePythonAction`(executer 호출).

### 3-3. 액션 실행 엔진 (`cobot_core` 내부 클래스)

| 구성요소 | 위치 | 책임 |
|---|---|---|
| `ActionManager` | actions/action_manager.py | 액션 이름 → 구현 디스패치, 비전 서비스(`/get_3d_position`) 호출, 카메라→베이스 좌표 변환, 실패 시 안전 처리 |
| `BaseAction` | actions/base_action.py | 모든 로컬 액션의 추상 베이스(`execute()`), `reset()`/`clear_alarm()` 유틸 |
| `DSRobotController` | controller/dsr_controller.py | DSR_ROBOT2 API 래퍼 — movel/movej/주기모션, 컴플라이언스/힘제어, 그리퍼 |
| `VisionStrategy` | actions/vision_strategy.py | coarse-to-fine 비주얼 서보잉(거친 검출 → 카메라 정렬 → 정밀 재검출) |
| `RG` (그리퍼) | controller/onrobot.py | OnRobot RG2 그리퍼 Modbus TCP 제어 (192.168.1.1:502) |

**로컬 액션 25종** (`actions/logical_actions/*.py`) — 한 줄 요약:

| 액션 | 동작 |
|---|---|
| pick_vertical / pick_horizontal / pick_side | 수직 / 수평(손목 비틀기) / 측면 접근 그랩 |
| place | 지정 박스(left/right)로 이동 후 놓기 |
| approach / detect_in_place / finding / search | 대상 접근·정지검출·이동탐색·관절스캔 |
| pour / shake / stir / spread / squeeze | 따르기 / 흔들기 / 젓기 / 펴 바르기 / 짜기 |
| tap / push / press | 두드리기 / 밀기 / 힘제어로 누르기 |
| open_cap / close_cap | 뚜껑 풀기 / 잠그기 (컴플라이언스) |
| flip / trash / check_grip / hello_bot | 뒤집기 / 버리기 / 그립 확인 / 데모 인사 |
| reset / stop / clear_alarm | 홈 복귀 / 비상 정지 / 알람 해제 |

> 디스패치 경로: `execute_command` → `Executer` → `ActionManager.perform(action)` → 로컬 액션 `execute()` → `DSRobotController`(모션) / `RG`(그리퍼).

### 3-4. 비전 / 그래스핑 (`main_side/object_detection`, `main_side/gripper_approaching_sequence`)

| 노드 / 모듈 | 위치 | 책임 | 인터페이스 |
|---|---|---|---|
| `img_node` | object_detection/realsense.py | RealSense 컬러/깊이/인트린식 프레임 캐싱 | sub: `/camera/.../color` `/aligned_depth` `/camera_info` |
| `object_detection` | object_detection/detection.py | YOLO 검출 + 깊이→3D 변환, 검출 서비스 제공 | **Service**: `/get_3d_position` (od_msg/GetTargetPose) · pub: `/detection`, 시각화 compressed |
| `YoloModel` | object_detection/yolo.py | YOLO11s 추론, 다중 프레임 합의(IoU+다수결) | — |
| `semantic_grasp_node` | gripper_approaching_sequence/grasp_node.py | YOLO→(plate는 VLM ROI)→깊이필터→PCA 자세→DSR 모션까지 풀 그랩 사이클 | **Service**: `/semantic_grasp` (std_srvs/Trigger) |
| `VLMClient` | gripper_approaching_sequence/vlm_client.py | OpenAI 비전(GPT-4o)으로 잡을 면 ROI 추정 (plate 전용) | OpenAI API |
| `grasp_geometry` | gripper_approaching_sequence/grasp_geometry.py | 깊이 필터·2D→3D·PCA 그랩 자세 계산 (numpy) | — |
| `DoosanGripperMotion` | gripper_approaching_sequence/motion.py | pre-grasp→target→close→lift 모션 시퀀스 + 핸드아이 좌표 변환 | DSR_ROBOT2 / Modbus |

> 인터페이스 정의: `interfaces/command/Command.action`(시퀀스 실행), `interfaces/od_msg/srv/GetTargetPose.srv`·`SrvDepthPosition.srv`(대상 3D 좌표).

### 3-5. 공용 유틸 (`common/utils/rokey/basic`)

| 노드 | 위치 | 책임 |
|---|---|---|
| `service_client_node` | get_current_pos.py | 현재 TCP/관절 자세 조회·표시 (수동 티치) |
| `dsr_rokey_basic_py` | jog_complete.py | Tkinter Jog GUI — 관절/직교 이동, 그리퍼 I/O, Z축 정렬(핸드아이 캘리브용) |

---

## 4. 런치 & 설정

- `cobot_bringup/launch/system.launch.py` — 기동 순서: `executer` → `state_manager` → `ui_bridge` → `object_detection` → `voice_to_command` → `voice_client` → (4초 지연 후) `bt_manager`.
- `cobot_bringup/launch/core_vision.launch.py` — 코어+비전만.
- `gripper_approaching_sequence/launch/grasp.launch.py` — 그랩 단독 테스트(옵션으로 RealSense 포함).
- `cobot_bringup/config/params.yaml` — 모션 속도/가속, 그리퍼 오프셋, 깨우기 임계값, LLM/TTS 모델 등 노드별 파라미터.

---

## 5. 핵심 토픽 / 서비스 / 액션 한눈에

| 종류 | 이름 | 타입 | 생산자 → 소비자 |
|---|---|---|---|
| Topic | `/voice_command` | std_msgs/String (JSON 배열) | 음성 → bt_manager, ui_bridge |
| Topic | `/voice_reply` | std_msgs/String | 음성 → 웹 백엔드/voice_client (TTS) |
| Topic | `/wakeup_status` `/stt_result` | std_msgs/String | 음성 → 웹 UI |
| Topic | `/admin_command` | std_msgs/String (ESTOP/UNLOCK) | 관리자 → bt_manager, state_manager |
| Topic | `/status` | std_msgs/String | bt_manager → 음성/ui_bridge |
| Topic | `/detection` | std_msgs/String (JSON) | object_detection → ui_bridge |
| Action | `execute_command` | command/Command | bt_manager(client) → executer(server) |
| Service | `/get_3d_position` | od_msg/GetTargetPose | executer → object_detection |
| Service | `/semantic_grasp` | std_srvs/Trigger | (테스트) → semantic_grasp_node |
| Service | `/dsr01/...` | dsr_msgs2/* | state_manager → Doosan 컨트롤러 |

---

*문서 작성: 코드베이스 전수 검토 기반. 경로 참조/빌드 구조 이슈는 본 문서에서 다루지 않음.*
