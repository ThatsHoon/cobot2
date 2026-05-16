# cobot2 노드 통합 설계 (확정 v2)

> 최종 결정 반영. 목표: 런타임 **~14 노드 → 7 노드**, 집기는 **분석 기반 자동대응**으로 일원화.
> 결정: ① wake 억제 = 상태 기반 대응 시나리오 신설 ② 음성 = `wakeup_worker` 단독 ③ 집기 = cobot_core 기존 비전·집기 제거 후 `gripper_approaching_sequence` 구조로 대체 ④ BT 유지.

---

## 1. 통합 후 런타임 노드 (7개)

| # | 노드 | 패키지 | 책임 |
|---|---|---|---|
| 1 | `wakeup_worker_node` | sub1_side/web/backend | 음성 두뇌 — wake→STT→LLM, **상태 게이트 포함** |
| 2 | `client_bridge_node` | sub1_side/web/backend | ROS↔WS 브리지 + TTS 프록시 (UI 단일 입출구) |
| 3 | `bt_manager` (C++) | main_side/bt_manager | `/voice_command`→큐→`execute_command` (유지) |
| 4 | `command_executer` | main_side/cobot_core | 시퀀스 스텝 실행 (집기 외 모션 소유) |
| 5 | `state_manager` | main_side/cobot_core | `/admin_command` ESTOP/UNLOCK 하드웨어 정지 |
| 6 | `ui_bridge_node` | main_side/cobot_core | 상태 집계 → `/ui_bridge/state` (UI·게이트 단일 소스) |
| 7 | `grasp_perception_node` | main_side/gripper_approaching_sequence | **인지+집기 통합** — 검출→VLM→포인트클라우드 해석→그리퍼 자동대응 + 접근·파지 모션 |

---

## 2. ① 음성 — `wakeup_worker` 단독 + 상태 대응 시나리오

### 2-1. 제거
- `voice_processing` 패키지 전체 삭제 (`voice_to_command`, `voice_client`). **fallback 없음.**
- TTS 재생은 프론트엔드 `/tts` 엔드포인트가 전담.
- 공유 LLM 프롬프트(`voice_processing/prompt.py` ↔ `wakeup_worker.py` 중복)는 `common/`으로 단일화 후 `wakeup_worker`가 참조.

### 2-2. wake 억제 — 상태 기반 대응 시나리오 (신설)
`wakeup_worker`가 `/ui_bridge/state` 단일 구독으로 로봇 상태를 받아 wake 감지를 게이팅한다. 위치: `wakeup_worker.py`의 wake 감지 → 명령 파싱 사이에 `_gate_by_state()` + 상태 콜백 신규 추가.

| 로봇 상태 | wake 감지 시 대응 시나리오 |
|---|---|
| **IDLE** | 정상 — 녹음→STT→LLM→`/voice_command` 발행 |
| **RUNNING** | 일반 명령 억제. wake 감지 시 **짧은 STT 1회**만 수행 → 인터럽트 키워드("정지/멈춰/스톱") → `/admin_command{ESTOP}` 발행. 그 외 → 무시 + `/voice_reply`로 "작업 중입니다, 잠시 후 다시 말씀해 주세요" 안내(웹 TTS) |
| **PAUSED / ERROR** | 일반 명령 억제. 복구 키워드("재개/해제/언락") → `/admin_command{UNLOCK}`. 그 외 무시 + 상태 안내 음성 |

→ 동작 중 오인식으로 작업이 가로채이는 것을 막으면서, 음성만으로 비상정지·복구가 가능한 안전 시나리오.

---

## 3. ② 비전+집기 — 고정 grasp만 제거, 동적 pick으로 대체 (BT 변칙 대응 보존)

> **원칙**: bt_manager의 변칙 대응(탐색·접근·잡힘검증)은 BT 노드로 유지한다.
> 제거 대상은 **고정 grasp 전략 3종뿐**이며, 이를 분석 기반 단일 동적 `pick`으로 대체한다.

### 3-1. cobot_core에서 제거 (최소 범위)
- **제거**: `pick_vertical`, `pick_horizontal`, `pick_side` (객체별 고정 grasp 전략 3종) → 단일 동적 `pick`으로 대체
- **제거**: `actions/vision_strategy.py`의 coarse_to_fine 비주얼 서보잉 (동적 pick이 VLM→포인트클라우드로 대체)
- **유지 (BT 변칙 대응 본체)**: `finding`, `search`, `detect_in_place`, `approach`, `check_grip` — bt_cobot2.xml의 SearchLogic·GripVerification이 직접 사용. 단, 타겟 위치 소스만 통합 perception `GraspObject(mode="locate")`로 교체.
- **`action_manager.py` 정리**: `/get_3d_position` 클라이언트 → `GraspObject` 클라이언트로 교체 (제거가 아니라 교체. finding/approach 등이 계속 호출).
- **리소스 이동**: `cobot_core/resource/T_gripper2camera.npy` → `gripper_approaching_sequence/resource/`.
- `object_detection` 노드/패키지 삭제, YOLO 추론은 `gripper_approaching_sequence/perception.py`의 `YoloDetector`로 일원화. 카메라 `ImgNode`도 단일화.

### 3-1b. BT 변칙 대응 흐름 (불변 — 보존 확인)
```
PopNextTask → IsTargetRequired?
  ├─ SearchLogic: IsTargetLocated → detect_in_place → finding   (소스: GraspObject locate)
  ├─ approach                                                    (소스: GraspObject locate)
  └─ 실제 액션: pick(동적) / place·trash·shake·pour(고정) ...
  └─ (no target) check_grip                                      (잡힘 검증)
estop_flag → 큐 플러시 (admin_command)
```
→ bt_manager가 "탐색 실패 시 재탐색→접근→실행" 변칙 대응을 계속 주관. 동적 pick은 *최종 grasp*만 담당.
부수 정리: `IsObjectGripped`(데드 노드) 트리에서 제거 또는 GripVerification에 연결.

### 3-2. `grasp_perception_node` (gripper_approaching_sequence) — 분석 기반 자동대응
`semantic_grasp_node.run_once`를 일반화하여 서비스화:

1. YOLO 검출 (대상 클래스)
2. VLM 의미 해석 — 잡을 부위/면 ROI
3. **포인트클라우드 구조 자동 판정** — 깊이 필터→3D 클라우드→PCA 고유값으로 평면/원통/구/불규칙 구조 자동 분류 (기존 `grasp_geometry`의 radial/cylindrical/spherical 분기를 **클래스 의존이 아닌 구조 기반 자동 분기**로 일반화)
4. **그리퍼 자동대응** — 구조 결과로 grip width·force·접근축 자동 산출
5. `mode="grasp"`면 `DoosanGripperMotion`으로 접근·파지까지 수행, `mode="locate"`면 pose만 반환(모션 없음)

### 3-3. 신 인터페이스 (신규 srv, 기존 deprecate)
`od_msg/srv/GraspObject.srv` 신설. 기존 `GetTargetPose`/`SrvDepthPosition` 폐기.
```
# Request
string target_name
string mode          # "grasp" = 인지+파지 실행 | "locate" = pose만 반환
---
# Response
bool success
string message
geometry_msgs/Pose grasp_pose
float64 width_mm
float64 quality
```

### 3-4. cobot_core 액션 매핑 (동적 vs 고정 vs 변칙)
- **동적 pick (신규)**: `pick_vertical/horizontal/side` → 단일 `pick`. `GraspObject(mode="grasp")` 블로킹 호출 → 인지(YOLO·VLM·포인트클라우드)·최종 파지 모션을 `grasp_perception_node`가 수행.
- **변칙 대응 (유지·소스 교체)**: `finding`·`search`·`detect_in_place`·`approach`·`check_grip` 유지. BT가 직접 틱. 타겟 위치는 `GraspObject(mode="locate")` 응답(pose) 사용. `approach`는 코스 사전위치(cobot_core 모션), `pick`은 그 후 정밀 grasp.
- **고정 시퀀스 (유지)**: `place`·`trash`·`shake`·`pour`·`tap`·`reset`·`stir`·`spread`·`squeeze`·`press`·`push`·`flip`·`open_cap`·`close_cap`·`hello_bot`·`stop`·`clear_alarm` → 그대로. (`tap`만 `GraspObject(mode="locate")`로 pose 취득 후 타격 모션은 cobot_core 유지)

### 3-5. 로봇 모션 소유권 (충돌 방지 contract)
- **정밀 grasp(최종 접근+파지)** = `grasp_perception_node`(`DoosanGripperMotion`) 소유.
- **코스 approach + 고정 시퀀스 모션** = `command_executer`/`DSRobotController` 소유.
- BT는 `approach`(코스, cobot_core) → `pick`(정밀, grasp_node) 순서로 **다른 스텝**에 배치하고 각 스텝이 블로킹이라 동시 DSR 제어 없음 → 소유권이 스텝 경계에서 깔끔히 이양.

### 3-6. LLM 프롬프트 / 시퀀스 정합 (필수 개정)
- 정본 프롬프트(`wakeup_worker.py` PROMPT_CONTENT)의 **"객체별 잡는 방식 고정"(apple→pick_vertical …) 매핑 삭제** → `pick_vertical/horizontal/side` 카탈로그를 단일 `pick(target)`로 통합. 잡는 방식은 grasp_node가 자동 결정하므로 LLM이 결정하지 않음.
- 모든 예시(`사과 버려줘` 등)의 `pick_*` → `pick`으로 갱신. `finding`/`tap`/고정 액션 규칙은 유지.
- 구식 `voice_processing/resource/sequence.json`(이미 `pick`/`place "쓰레기통"` 사용, 프롬프트와 드리프트)은 패키지 제거와 함께 폐기 — text_to_command 오프라인 도구가 필요하면 `common/`으로 신 포맷 재작성.

---

## 4. ③ BT / 오케스트레이션 — 유지

`bt_manager`·`command_executer`·`state_manager`·`ui_bridge_node` 구조 유지. 변경점:
- `action_manager`의 비전 호출 → `GraspObject` 클라이언트로 교체.
- `ui_bridge`는 상태 집계 단일 소스 (UI + wake 게이트 양쪽 공급).

---

## 5. 영향도 체크 매트릭스

| 변경 | 영향 파일 | 조치 |
|---|---|---|
| `voice_processing` 제거 | `cobot_bringup/launch/system.launch.py`, `config/params.yaml` | 노드·파라미터 블록 삭제 |
| 공유 프롬프트 | `wakeup_worker.py`, (구)`prompt.py` | `common/`으로 이동·참조 |
| wake 게이트 신설 | `wakeup_worker.py` | `/ui_bridge/state` 구독 + `_gate_by_state()` 추가 |
| 고정 grasp 제거 | `logical_actions/{pick_vertical,pick_horizontal,pick_side}.py`, `vision_strategy.py` | 삭제, 단일 동적 `pick` 액션 추가 |
| 변칙 대응 보존·소스 교체 | `logical_actions/{finding,search,detect_in_place,approach,check_grip}.py`, `action_manager.py` | **유지**. 위치 소스 `/get_3d_position`→`GraspObject(locate)` 클라이언트로 교체 |
| `tap` 비전 의존 | `logical_actions/tap.py` | `GraspObject(mode=locate)` 사용으로 수정 |
| BT 데드 노드 | `bt_cobot2.xml` | `IsObjectGripped` 트리에서 제거 또는 GripVerification에 연결 |
| 인터페이스 교체 | `interfaces/od_msg` | `GraspObject.srv` 추가, `GetTargetPose`/`SrvDepthPosition` 제거, `command/Command.action` 유지 |
| 핸드아이 리소스 이동 | `cobot_core/resource/T_gripper2camera.npy` | `gripper_approaching_sequence/resource/`로 이동, 참조 갱신 |
| `object_detection` 삭제 | `launch/{system,core_vision}.launch.py`, `ui_bridge.py`(`/detection`), `od_msg` | grasp 노드로 교체, 검출 토픽 소스 갱신 |
| LLM 프롬프트 개정 | `wakeup_worker.py` PROMPT_CONTENT | `pick_*`+객체별 고정매핑 → 단일 `pick`, 예시 갱신 |
| 구식 시퀀스 폐기 | `voice_processing/resource/sequence.json` | 패키지와 함께 제거(드리프트) |

> CLAUDE.md 규칙: 수정 시점마다 소비처 grep 재확인, 엣지 케이스(빈 검출/타임아웃/실패/상태 전이) 점검, "타 기능 영향 없음" 자체 검증 보고.

---

## 6. 구현 순서

1. **음성 단순화** (저위험·독립): `voice_processing` 제거 → 프롬프트 `common` 이동 → launch/params 정리
2. **wake 게이트**: `/ui_bridge/state` 구독 + 상태 대응 시나리오 구현
3. **인터페이스**: `GraspObject.srv` 신설, 구 srv 제거
4. **동적 pick 통합** (고영향): `grasp_perception_node` 서비스화 → 고정 grasp 3종+`vision_strategy` 제거, 단일 `pick` 추가 → `finding/search/detect_in_place/approach/check_grip` 위치 소스만 `GraspObject(locate)`로 교체(BT 변칙 대응 보존) → 프롬프트 개정 → 핸드아이 리소스 이동
5. **launch/params 최종 정리** + 통합 검증 (E2E: 음성→BT 변칙대응→executer→동적 pick/고정 시퀀스→모션)

---

*본 문서 = 통합 청사진. 코드 수정은 순서대로, 단계마다 영향도 재검증·보고.*
