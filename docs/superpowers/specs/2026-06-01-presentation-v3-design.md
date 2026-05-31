# cobot2-homie Presentation v3 — Design Spec

**Date**: 2026-06-01  
**Output**: `docs/presentation-v3/index.html`  
**Audience**: 포트폴리오 / 취업용 (채용 담당자, 기술 면접관)  
**Language**: 한국어  
**Structure**: 임팩트 퍼스트 (결과 먼저 → 원리 설명)  
**Slides**: 20장

---

## 1. 핵심 요건

| 항목 | 규격 |
|---|---|
| 가로세로 비 | 16:9 strict — `min(100vw, 100vh * 16/9)` letterbox |
| 최소 글씨 크기 | 18px (clamp 하한) |
| 헤더 위치 | 모든 슬라이드 최상단 (`kicker + h2`) |
| 아이콘 | Lucide (UI/컨셉) + simpleicons CDN (기술 스택) — 이모지 금지 |
| 슬라이드당 텍스트 | ≤ 40자 목표, GIF·이미지 중심 |
| 테마 | tokyo-night (기존 presentation-v2 와 동일) |
| 기반 파일 | `presentation-v2/assets/` CSS·JS 재사용 (`overrides.css` 신규 작성) |

---

## 2. 시각 자산 매핑

### 재사용 (presentation-v2/assets/media/)

| 파일 | 사용 슬라이드 |
|---|---|
| `cover-hero.png` | 1 표지 |
| YouTube `n7uikEVqS7M` | 2 시연 영상 |
| `demo-apple-{find,pick,trash}.gif` | 3 동작 데모 |
| `demo-shaker-{pick,shake,pour}.gif` | 3 동작 데모 |
| `social-background.png`, `market-trend.png` | 5 문제 정의 |
| `stt-code-snippet.png`, `stt-prompt-rule.png` | 10 음성 파이프라인 |
| `bt-groot-viewer.png` | 11 BT 오케스트레이션 |
| `vision-yolo-result.png`, `vision-classes.png` | 12 동적 파지 ① |
| `vision-workflow.png` | 13 동적 파지 ② |
| `vision-depth-tilt.png` | 15 핸드아이 캘리브레이션 |
| `demo-apple-trash.gif`, `demo-shaker-pour.gif` | 16 고정 행동 시퀀스 |
| `ui-admin-dashboard.gif`, `db-docker-structure.png` | 17 안전 + DB |
| `yolo-fitness-overview.png`, `vision-yolo-comparison.png` | 18 YOLO + 리팩터링 |

### 신규 제작 (/architecture-diagram 스킬)

| 파일명 | 슬라이드 | 내용 |
|---|---|---|
| `diagrams/arch-system.html` | 6 | 2 PC(sub1/main) + 7노드 + 토픽/액션 흐름 |
| `diagrams/arch-nodes.html` | 7 | 7노드 책임 분리 + 인터페이스 연결도 |
| `diagrams/arch-workflow.html` | 8 | wakeup→STT→BT→grasp→sequence 전체 워크플로우 |

---

## 3. 슬라이드별 설계

### Section 1 — Hook (1–4)

**슬라이드 1 · 표지**
- kicker: `DOOSAN ROBOTICS BOOTCAMP · ROKEY · B-2 TEAM`
- h2: `사람의 말을 알아듣고 손을 쓰는 협동로봇`
- 레이아웃: 좌측 `cover-hero.png` (60%), 우측 프로젝트명 + 기술 아이콘 5종 (ROS, Python, OpenAI, Docker, YOLO)
- 발표자 정보 없음

**슬라이드 2 · 시연 영상**
- kicker: `SECTION 01 · DEMO`
- h2: `시연 영상`
- 레이아웃: YouTube iframe 전면 (`https://www.youtube.com/embed/n7uikEVqS7M`)
- 한 줄 캡션: `"말 한마디로 집어서 옮기는 협동로봇"`

**슬라이드 3 · 6가지 실제 동작**
- kicker: `SECTION 01 · ACTION CATALOG`
- h2: `6가지 실제 동작 — 사과·후추통 데모`
- 레이아웃: 3×2 GIF 그리드, 각 셀에 라벨만 (Find / Pick / Trash / Pick-shaker / Shake / Pour)

**슬라이드 4 · 핵심 수치**
- kicker: `SECTION 01 · KEY METRICS`
- h2: `2주 만에 완성한 동작 가능한 시스템`
- 레이아웃: 메트릭 카드 4종 — `mAP 99.0%` / `F1 96.8%` / `7 ROS 노드` / `2주 개발`

---

### Section 2 — Why & What (5–9)

**슬라이드 5 · 문제 정의**
- h2: `왜 음성 인터페이스가 필요한가`
- 레이아웃: 좌 `social-background.png`, 우 `market-trend.png`, 2컬럼 각 1줄 설명

**슬라이드 6 · 시스템 아키텍처**
- h2: `두 PC, 한 명령 — 책임 분리 구조`
- 레이아웃: `diagrams/arch-system.html` iframe 전면
- 내용: sub1_PC(음성 UI) ↔ CycloneDDS ↔ main_PC(로봇) + 7노드 배치 + 토픽/액션 화살표

**슬라이드 7 · 노드 아키텍처**
- h2: `노드 7개 · 단일 책임 원칙`
- 레이아웃: `diagrams/arch-nodes.html` iframe 전면
- 내용: wakeup_worker / bt_manager / executer / state_manager / ui_bridge / grasp_perception_node / db_logger

**슬라이드 8 · 전체 워크플로우**
- h2: `발화부터 파지까지 — 단계별 흐름`
- 레이아웃: `diagrams/arch-workflow.html` iframe 전면
- 내용: 10단계 waterfall 다이어그램

**슬라이드 9 · 기술 스택**
- h2: `네 카테고리, 한 페이지 — 핵심 기술 스택`
- 레이아웃: 2×2 카드 (HARDWARE / AI / MIDDLEWARE / DEV), simpleicons CDN 아이콘
- HARDWARE: Doosan m0609, OnRobot RG2, RealSense D435
- AI: YOLO11s, GPT-4o, Whisper, openWakeWord
- MIDDLEWARE: ROS 2, BehaviorTree.CPP, CycloneDDS, Docker
- DEV: Python, C++, MySQL, FastAPI

---

### Section 3 — How It Works (10–16)

**슬라이드 10 · 음성 파이프라인**
- h2: `발화에서 JSON 명령까지 — 6초 흐름`
- 레이아웃: 좌측 STT 흐름 단계 (wakeup→녹음→Whisper→GPT-4o→JSON), 우 `stt-prompt-rule.png`

**슬라이드 11 · BT 오케스트레이션**
- h2: `한 명령이 여러 단계로 — BehaviorTree.CPP v3`
- 레이아웃: 좌 BT 구조 설명 (PopNextTask → SearchLogic → ExecutePythonAction), 우 `bt-groot-viewer.png`

**슬라이드 12 · 동적 파지 ① 탐색**
- h2: `1차 탐색 — YOLO로 목표 물체 발견`
- 레이아웃: 좌 탐색 과정 단계 카드, 우 `vision-yolo-result.png`
- 내용: 1차 탐색 위치 이동 → YOLO 탐지 → 물체 근처 이동

**슬라이드 13 · 동적 파지 ② 근접 재탐지**
- h2: `2차 탐색 — VLM ROI로 depth 오차 사전 예방`
- 레이아웃: 좌 흐름 (2차 위치 이동 → 재탐지 → VLM ROI 요청 → ROI×1.5), 우 `vision-workflow.png`

**슬라이드 14 · 동적 파지 ③ PCA 접근 계산**
- h2: `포인트클라우드 PCA — 물체 형상으로 그리퍼 각도 결정`
- 레이아웃: 좌 PCA 계산 단계 (포인트클라우드 추출 → 분포 분석 → 접근 벡터 산출 → 그리퍼 자세), 우 간단 시각 다이어그램 (인라인 SVG)

**슬라이드 15 · 핸드아이 캘리브레이션**
- h2: `카메라 좌표 → 베이스 좌표 — 5° 기울임의 해결`
- 레이아웃: 좌 `vision-depth-tilt.png`, 우 T_gripper2camera 4×4 행렬 + 1줄 설명

**슬라이드 16 · 고정 행동 시퀀스**
- h2: `파지 후 — 사전 설계된 고정 시퀀스 실행`
- 레이아웃: 좌 시퀀스 목록 카드 (place / trash / pour / shake / home), 우 `demo-apple-trash.gif` + `demo-shaker-pour.gif`

---

### Section 4 — Engineering Depth (17–18)

**슬라이드 17 · 안전 시스템 + DB 로깅**
- h2: `즉시 정지 + DB 격리 — 운영 안정성 설계`
- 레이아웃: 좌 ESTOP 3단 정지 흐름 (move_stop → drl_stop → RECOVERY) + `ui-admin-dashboard.gif`, 우 DB Docker 격리 구조 + `db-docker-structure.png`

**슬라이드 18 · YOLO 학습 + 리팩터링**
- h2: `데이터 정제 + 아키텍처 통합 — 품질 개선 과정`
- 레이아웃: 좌 `vision-yolo-comparison.png` + fitness 0.65→0.93 수치, 우 14노드→7노드 비교 표

---

### Section 5 — Close (19–20)

**슬라이드 19 · 도전과제 & 해결**
- h2: `네 가지 함정 · 네 가지 해결`
- 레이아웃: 2×2 카드
  - BT recursion 위험 → KeepRunningUntilFailure 패턴
  - depth 오차 → 2차 근접 재탐지
  - VLM latency → 2차 탐지 후 1회만 호출
  - DDS 멀티캐스트 불안정 → CycloneDDS 유니캐스트

**슬라이드 20 · 마무리 / Q&A**
- h2: `감사합니다 — 질문 환영합니다`
- 레이아웃: 중앙 정렬, GitHub 링크 (simpleicons), 배운 점 3줄

---

## 4. 구현 순서

1. **아키텍처 다이어그램 3종 제작** (`/architecture-diagram` 스킬) → `docs/presentation-v3/diagrams/`
2. **기본 HTML PPT 뼈대 생성** (`/html-ppt` 스킬, tokyo-night, presenter-mode-reveal)
3. **20 슬라이드 마크업** — 순서대로 index.html 작성
4. **overrides.css** — 16:9 strict letterbox, 슬라이드별 레이아웃 오버라이드, clamp 폰트
5. **시각 자산 복사** — `presentation-v2/assets/media/` → `presentation-v3/assets/media/` symlink 또는 복사
6. **검증** — 브라우저 1920×1080 / 1280×720, 이모지 grep 0, 최소 폰트 18px 확인

---

## 5. 파일 구조

```
docs/presentation-v3/
├── index.html
├── assets/
│   ├── base.css        (presentation-v2 에서 복사)
│   ├── fonts.css
│   ├── runtime.js
│   ├── themes/tokyo-night.css
│   ├── overrides.css   (신규)
│   └── media/          (presentation-v2/assets/media/ 재사용)
└── diagrams/
    ├── arch-system.html
    ├── arch-nodes.html
    └── arch-workflow.html
```
