# Semantic Grasping (m0609)

YOLO + OpenAI vision + RealSense depth + PCA → 객체별 동적 그리퍼 자세 산출.

## 흐름

```
RealSense color/aligned_depth/intrinsics
    │
    ▼
YOLO bbox  →  crop  →  VLM(gpt-4o)  →  grasp ROI bbox
                                        │
            ┌───────────────────────────┘
            ▼
   depth filter (median ±5cm + MAD)
   2D→3D (intrinsics)
   PCA: principal axis / normal / eigvals
   width = bbox 점운의 x_axis 분포
            │
            ▼
   cam → gripper(hand-eye) → base
   pre-grasp(−10cm) → target → close → lift(+15cm)
```

## 구조

```
                ┌─ ros2 service /semantic_grasp ─┐    ┌─ python3 grasp_gui.py ─┐
   Entry        │   (Trigger srv)                │    │   (Tkinter 디버거)      │
                └────────────────┬───────────────┘    └────────────┬───────────┘
                                 │                                 │
                                 ▼                                 │
                    ┌─────────────────────────────┐                │
   Orchestrator     │     grasp_node.py (rclpy)   │                │
                    │  SemanticGraspNode          │                │
                    │  /semantic_grasp svc        │                │
                    └──┬──────┬─────────┬──────┬──┘                │
                       │      │         │      │   ┌───────────────┘
                       │      │         │      │   │ (직접 import)
                    ┌──▼──┐ ┌─▼───┐ ┌───▼──┐ ┌─▼───▼─┐
   Modules          │per- │ │vlm_ │ │grasp_│ │motion │
                    │cep- │ │cli- │ │geo-  │ │       │
                    │tion │ │ent  │ │metry │ │       │
                    │     │ │     │ │(num- │ │       │
                    │     │ │     │ │ py)  │ │       │
                    └──┬──┘ └──┬──┘ └──────┘ └───┬───┘
                       │       │                 │
                    ┌──▼────┐ ┌▼─────────┐  ┌────▼──────────┐
   External         │RealS- │ │OpenAI    │  │Doosan m0609   │
   (외부 의존)      │ense   │ │vision    │  │+ OnRobot RG   │
                    │ROS    │ │gpt-4o    │  │DSR_ROBOT2     │
                    │topics │ │HTTPS+JSON│  │+ Modbus TCP   │
                    └───────┘ └──────────┘  └───────────────┘

데이터 타입 (모듈 간):
   perception   →  Detection(box_xyxy, score, class_name)
   vlm_client   →  GraspROI(bbox, reason, prompt)
   grasp_geom.  →  GraspPose(position, rotation, width, eigvals,
                              tilt_deg, planarity, linearity, ...)
   motion       →  GraspExecutionResult(success, target/pre base pose)

의존 그래프 (import):
   grasp_node ──→ perception, vlm_client, grasp_geometry, motion
   motion     ──→ grasp_geometry  (DSR_ROBOT2/onrobot 은 lazy import)
   grasp_geometry  ← leaf (numpy 만 의존, ROS 없음 → 단위 테스트 가능)
   grasp_gui  ──→ 위 4개 + tkinter (별도 entry, ros2 run 안 씀)
```

## 모듈 (`gripper_approaching_sequence/`)

| 파일 | 책임 |
|---|---|
| `perception.py` | RealSense 캐시 (`ImgNode` 재사용) + YOLO 추론 |
| `vlm_client.py` | OpenAI vision (JSON 모드, 영문 중립 프롬프트) |
| `grasp_geometry.py` | depth filter / 2D→3D / PCA / pose / 각도 분석. **numpy 전용**, ROS 의존 없음 |
| `motion.py` | DSR_ROBOT2 movel + OnRobot RG width 제어. `setup_dsr(node)` + `dryrun=True` |
| `grasp_node.py` | rclpy 오케스트레이터, `/semantic_grasp` (Trigger) |
| `gui_for_test/grasp_gui.py` | Tkinter 클릭 디버거. 단계별 이미지 자동 저장 |

## 핵심 결정

- **Depth 토픽**: `aligned_depth_to_color` (color/depth 픽셀 정렬 필수)
- **단위**: 모듈 내부 m, motion 경계에서 mm. hand-eye matrix translation 도 mm
- **법선 추정**: BBox / ROI×1.6 / ROI 단일 — 세 후보 PCA 결과 중 planarity 최댓값 자동 채택 (가림 객체 fallback)
- **VLM 응답**: `response_format=json_object` 강제 + 영문 중립 프롬프트 (한국어 거부 회피)
- **로봇 식별자**: `ROBOT_ID="dsr01"`, `ROBOT_MODEL="m0609"` 고정
- **Hand-eye matrix**: `cobot_core/resource/T_gripper2camera.npy` 재사용

## 좌표계

| 위치 | frame | 단위 |
|---|---|---|
| `grasp_geometry` | camera optical | m |
| `T_gripper2camera.npy` translation | — | mm |
| `motion.py` 출력 (DSR pose) | base | mm, deg, ZYZ |

## 실행

```bash
# (A) GUI 디버그 — 카메라만, 클릭으로 단계별 검증
ros2 launch realsense2_camera rs_align_depth_launch.py align_depth.enable:=true ...
python3 gui_for_test/grasp_gui.py

# (B) 실로봇 풀 사이클 — 4 터미널 가이드
./scripts/start_session.sh

# (C) launch 한 번에
ros2 launch gripper_approaching_sequence grasp.launch.py \
    target_class:=glasses include_realsense:=true gripper_ip:=192.168.1.1
ros2 service call /semantic_grasp std_srvs/srv/Trigger {}

# (D) dryrun (좌표 변환만)
ros2 run gripper_approaching_sequence grasp_dryrun --target glasses
```

`OPENAI_API_KEY` 는 `~/.bashrc` 에 export 되어 있어야 함.

## Hand-Eye 캘리브레이션 (필요 시)

1. `ros2 service call /dsr01/system/set_robot_mode dsr_msgs2/srv/SetRobotMode "robot_mode: 0"` — 직접교시 ON
2. `ros2 run rokey get_current_pos` — 좌표 표시 GUI
3. 마커 + `cv2.calibrateHandEye()` 로 4×4 행렬 산출 (translation **mm**)
4. `cobot2/cobot_core/resource/T_gripper2camera.npy` 로 저장 → `colcon build --packages-select cobot_core`

## 디렉토리

```
gripper_approaching_sequence/
├── package.xml, setup.py, setup.cfg
├── launch/grasp.launch.py
├── scripts/start_session.sh
├── gripper_approaching_sequence/   ← 5 모듈 (위 표 참조)
├── gui_for_test/
│   ├── grasp_gui.py
│   └── history_images/{ts}_{class}/   ← 클릭마다 자동 저장
│       ├── 00_prompt.txt
│       ├── 01_live.jpg
│       ├── 02_crop.jpg
│       ├── 03_vlm_roi.jpg, 03_vlm_response.json
│       ├── 04_depth_heatmap.jpg
│       ├── 05_annotated_full.jpg, 05_annotated_view.jpg
│       ├── 06_pose_info.txt
│       └── 07_pose.json
└── dev-docs/README.md
```

## 상태

| 항목 | 상태 |
|---|---|
| 퍼셉션 (YOLO + VLM + PCA) | ✅ |
| Pose 산출 + 각도 분석 (tilt/azimuth/p-yaw, planarity, linearity) | ✅ |
| Hand-eye + base 좌표 변환 | ✅ |
| 실로봇 motion (movel pre-grasp/target/lift) | ✅ |
| OnRobot RG2/RG6 width 제어 | ✅ |
| GUI 디버거 + 자동 이력 저장 | ✅ |
| `/semantic_grasp` Trigger 서비스 | ✅ |
| 자동 fallback (BBox/ROI×1.6/ROI) | ✅ |
| MoveIt2 충돌 검사 | ☐ |
| 커스텀 srv (target 인자 + 상세 결과) | ☐ |
| Multi-finger / suction 분기 | ☐ |
| VLM 거부 시 retry-with-rewording | ☐ |

## 운영 노트

- **로봇 모드**: `robot_mode 0` (manual) 에선 `movel` 거부 → 자동 실행 전 mode 1 필수
- **OnRobot 미연결**: `--gripper-ip` 빈 값이면 그리퍼 명령 no-op (안전)
- **가림 객체**: 손이 30%+ 가리면 BBox 후보 탈락 → ROI fallback (자동)
- **cv2 한글/°**: 캔버스 라벨은 ASCII (` deg`), Tkinter 로그/패널은 정상
