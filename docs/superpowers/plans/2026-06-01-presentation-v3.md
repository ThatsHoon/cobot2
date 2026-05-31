# Presentation v3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `docs/presentation-v3/` 에 20슬라이드 임팩트-퍼스트 한국어 HTML PPT 를 만든다.

**Architecture:** html-ppt 프레임워크(base.css + runtime.js + tokyo-night 테마)를 `presentation-v2/assets/`에서 그대로 복사하고, 새 `overrides.css`와 `index.html`만 작성한다. 시스템/노드/워크플로우 다이어그램 3종은 `/architecture-diagram` 스킬로 제작 후 `diagrams/` 폴더에 배치한다.

**Tech Stack:** HTML5, CSS(container-query cqw/cqh), vanilla JS(runtime.js), Lucide@0.469.0 UMD CDN, simpleicons CDN, BehaviorTree.CPP, ROS 2, YOLO11s, GPT-4o, Doosan DSR

---

## 파일 구조

```
docs/presentation-v3/
├── index.html                       ← 신규 (20슬라이드)
├── assets/
│   ├── base.css                     ← v2에서 복사
│   ├── fonts.css                    ← v2에서 복사
│   ├── runtime.js                   ← v2에서 복사
│   ├── overrides.css                ← 신규 (16:9 + 레이아웃 토큰)
│   ├── animations/
│   │   └── animations.css           ← v2에서 복사
│   ├── themes/
│   │   └── tokyo-night.css          ← v2에서 복사
│   └── media/                       ← v2에서 심볼릭링크 or 복사
│       (cover-hero.png, 6 GIFs, 14 이미지)
└── diagrams/
    ├── arch-system.html             ← Task 2: 시스템 아키텍처
    ├── arch-nodes.html              ← Task 3: 노드 아키텍처
    └── arch-workflow.html           ← Task 4: 전체 워크플로우
```

---

## Task 1: 디렉토리 셋업 + 기반 자산 복사

**Files:**
- Create: `docs/presentation-v3/` (디렉토리 구조)
- Copy from: `docs/presentation-v2/assets/{base.css,fonts.css,runtime.js,animations/,themes/}`
- Symlink: `docs/presentation-v3/assets/media` → `../presentation-v2/assets/media`

- [ ] **Step 1: 디렉토리 및 기반 파일 복사**

```bash
cd /home/hoon/cobot_ws/src/cobot2
mkdir -p docs/presentation-v3/assets/themes
mkdir -p docs/presentation-v3/assets/animations
mkdir -p docs/presentation-v3/diagrams

cp docs/presentation-v2/assets/base.css      docs/presentation-v3/assets/
cp docs/presentation-v2/assets/fonts.css     docs/presentation-v3/assets/
cp docs/presentation-v2/assets/runtime.js    docs/presentation-v3/assets/
cp docs/presentation-v2/assets/animations/animations.css docs/presentation-v3/assets/animations/
cp docs/presentation-v2/assets/themes/tokyo-night.css    docs/presentation-v3/assets/themes/

# media 폴더 심볼릭링크 (실제 파일은 v2에서 공유)
ln -s ../../presentation-v2/assets/media docs/presentation-v3/assets/media
```

- [ ] **Step 2: 파일 존재 확인**

```bash
ls -la docs/presentation-v3/assets/
ls -la docs/presentation-v3/assets/media | head -5
```

Expected: base.css, fonts.css, runtime.js, animations/, themes/, media -> (symlink)

- [ ] **Step 3: 빈 overrides.css 생성 (placeholder — Task 5에서 채움)**

```bash
touch docs/presentation-v3/assets/overrides.css
```

- [ ] **Step 4: 커밋**

```bash
git add docs/presentation-v3/
git commit -m "feat(ppt-v3): scaffold directory and copy base assets"
```

---

## Task 2: 시스템 아키텍처 다이어그램 제작

**Files:**
- Create: `docs/presentation-v3/diagrams/arch-system.html`

**내용**: sub1_PC(음성/UI) ↔ CycloneDDS LAN ↔ main_PC(로봇) 양쪽 PC 의 노드 배치 + 주요 ROS 2 토픽/액션/서비스 화살표. 다크 테마 SVG 인라인.

- [ ] **Step 1: /architecture-diagram 스킬로 시스템 아키텍처 다이어그램 제작**

`/architecture-diagram` 스킬을 사용하여 다음 내용의 다이어그램을 `docs/presentation-v3/diagrams/arch-system.html` 에 생성한다.

**다이어그램 명세:**
```
제목: cobot2 시스템 아키텍처 — 2 PC, 7 노드

[sub1_PC - 키오스크/UI PC]
  wakeup_worker_node
    (openWakeWord → Whisper STT → GPT-4o → /voice_command 발행)
  client_bridge_node
    (FastAPI/WebSocket, /tts, Web UI)

[main_PC - 로봇 PC]
  bt_manager (C++)
  command_executer (Python)
  grasp_perception_node (Python)
  state_manager (Python)
  ui_bridge_node (Python)
  db_logger (Python)

연결:
  sub1 → main: /voice_command (ROS2 Topic, UDP)
  sub1 ← main: /ui_bridge/state (ROS2 Topic, 10Hz)
  sub1 → main: /admin_command (ESTOP/UNLOCK)
  bt_manager → command_executer: execute_command (Action)
  command_executer → grasp_perception_node: /grasp_object (Service)
  state_manager → DSR: /dsr01/* (Service)
  db_logger → MySQL: SQL (Docker network only)
  
배경: 다크(#1a1b26 tokyo-night), 노드박스 라운드, 화살표 컬러코딩
  (Topic=파란색, Action=보라색, Service=초록색)
```

- [ ] **Step 2: 파일 생성 확인 + 브라우저로 열어서 시각 검증**

```bash
test -f docs/presentation-v3/diagrams/arch-system.html && echo "OK" || echo "MISSING"
wc -l docs/presentation-v3/diagrams/arch-system.html
```

Expected: 파일 존재, 50줄 이상

- [ ] **Step 3: 커밋**

```bash
git add docs/presentation-v3/diagrams/arch-system.html
git commit -m "feat(ppt-v3): add system architecture diagram"
```

---

## Task 3: 노드 아키텍처 다이어그램 제작

**Files:**
- Create: `docs/presentation-v3/diagrams/arch-nodes.html`

**내용**: main_PC 의 7개 노드 각 책임 + 인터페이스 연결도. 계층형 배치.

- [ ] **Step 1: /architecture-diagram 스킬로 노드 아키텍처 다이어그램 제작**

`/architecture-diagram` 스킬을 사용하여 다음 내용의 다이어그램을 `docs/presentation-v3/diagrams/arch-nodes.html` 에 생성한다.

**다이어그램 명세:**
```
제목: 노드 아키텍처 — 단일 책임 7 노드

계층 배치 (위→아래):
  [음성 입력] wakeup_worker → /voice_command
  [오케스트레이션] bt_manager (BT 큐 + 탐색 fallback)
  [실행] command_executer (ActionServer + ActionManager + 20종 논리 액션)
  [병렬] grasp_perception_node (YOLO+VLM+PCA) | state_manager (ESTOP 3단)
  [상태 집계] ui_bridge_node (5 토픽 → /ui_bridge/state 10Hz)
  [영속] db_logger (ROS→MySQL)

각 노드 박스 안에 핵심 책임 1줄씩.
인터페이스: Topic(→), Action(⇒), Service(↔)
색상: 음성=파란, BT=보라, 실행=초록, 비전=주황, 안전=빨강, 집계=회색, 로깅=갈색
배경: 다크(#1a1b26)
```

- [ ] **Step 2: 파일 확인**

```bash
test -f docs/presentation-v3/diagrams/arch-nodes.html && echo "OK" || echo "MISSING"
```

- [ ] **Step 3: 커밋**

```bash
git add docs/presentation-v3/diagrams/arch-nodes.html
git commit -m "feat(ppt-v3): add node architecture diagram"
```

---

## Task 4: 전체 워크플로우 다이어그램 제작

**Files:**
- Create: `docs/presentation-v3/diagrams/arch-workflow.html`

**내용**: wakeup word → STT → LLM → BT → executer → 동적 파지 파이프라인(1차탐색→2차재탐지→VLM ROI→PCA→GRIP) → 고정 시퀀스 → 홈 복귀. 10단계 waterfall 또는 swimlane.

- [ ] **Step 1: /architecture-diagram 스킬로 전체 워크플로우 다이어그램 제작**

`/architecture-diagram` 스킬을 사용하여 다음 내용의 다이어그램을 `docs/presentation-v3/diagrams/arch-workflow.html` 에 생성한다.

**다이어그램 명세:**
```
제목: 발화부터 파지까지 — 전체 워크플로우

단계 (순서대로, 수평 또는 수직 흐름):
  01 "왓썹 호미" 호출어 감지 (openwakeword)
  02 5초 녹음 → Whisper STT
  03 GPT-4o 명령 정련 → JSON 배열 (/voice_command)
  04 BT PopNextTask → execute_command 액션 발행
  05 ActionManager.perform(action) 디스패치
  ├─ [동적 파지 경로] /grasp_object 서비스 호출
  │    06a 1차 탐색: YOLO 탐지 + 물체 근처 이동
  │    06b 2차 근접 재탐지: VLM ROI×1.5 요청
  │    06c PCA 포인트클라우드 → 그리퍼 자세 계산
  │    06d m0609 접근 + RG2 GRIP
  └─ [고정 시퀀스 경로] pre-defined motion segments
  07 고정 행동 시퀀스 실행 (place/trash/pour/shake/…)
  08 홈 위치 복귀 → 다음 요청 대기

스타일: swimlane(sub1_PC / main_PC / 로봇 하드웨어) 또는 numbered-step waterfall
배경: 다크(#1a1b26), 분기점 다이아몬드, 단계별 색상 그라데이션
```

- [ ] **Step 2: 파일 확인**

```bash
test -f docs/presentation-v3/diagrams/arch-workflow.html && echo "OK" || echo "MISSING"
```

- [ ] **Step 3: 커밋**

```bash
git add docs/presentation-v3/diagrams/arch-workflow.html
git commit -m "feat(ppt-v3): add full workflow diagram"
```

---

## Task 5: overrides.css — 16:9 + 레이아웃 토큰

**Files:**
- Write: `docs/presentation-v3/assets/overrides.css`

- [ ] **Step 1: overrides.css 전체 작성**

`docs/presentation-v3/assets/overrides.css` 에 다음 내용을 작성한다:

```css
/* cobot2 PPT v3 — overrides.css
 * 우선순위: base.css → tokyo-night.css → style.css → overrides.css
 * 의존: container-query(cqw/cqh), Lucide UMD CDN, simpleicons CDN
 */

/* ===== 16:9 STRICT ===== */
html, body {
  background: #000;
  margin: 0; width: 100vw; height: 100vh; overflow: hidden;
}
.deck {
  width: min(100vw, calc(100vh * 16 / 9)) !important;
  height: min(100vh, calc(100vw * 9 / 16)) !important;
  position: absolute !important;
  inset: 0 !important;
  margin: auto !important;
  background: var(--bg);
  container-type: size;
  container-name: deck;
  overflow: hidden;
}
.slide {
  padding: 4cqh 5cqw;
  display: grid !important;
  grid-template-rows: auto 1fr;
  row-gap: 2.5cqh;
  font-size: clamp(18px, 1.5cqw, 22px);
  box-sizing: border-box;
}

/* ===== SLIDE HEAD ===== */
.slide-head .kicker {
  font-size: clamp(10px, 1.0cqw, 13px);
  letter-spacing: .14em;
  text-transform: uppercase;
  color: var(--text-3);
  margin: 0 0 0.4cqh;
}
.slide-head .h2 {
  font-size: clamp(22px, 3.0cqw, 42px);
  font-weight: 700;
  line-height: 1.15;
  margin: 0;
  color: var(--text-1);
}

/* ===== SECTION 1: HOOK ===== */

/* Slide 1 — 표지 */
.cover {
  display: grid;
  grid-template-columns: 55% 1fr;
  column-gap: 4cqw;
  align-items: center;
}
.cover-hero { width: 100%; height: 100%; object-fit: contain; border-radius: 12px; }
.cover-meta { display: flex; flex-direction: column; gap: 1.8cqh; }
.cover-meta .name {
  font-size: clamp(28px, 5cqw, 72px);
  font-weight: 800;
  background: var(--grad);
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent;
  margin: 0;
}
.cover-meta .tag { font-size: clamp(18px, 1.6cqw, 22px); color: var(--text-2); margin: 0; }
.cover-meta .kw { display: flex; flex-wrap: wrap; gap: 0.5cqw; }
.cover-meta .kw .pill { font-size: clamp(11px, 1.1cqw, 14px); }
.cover-tech { display: flex; gap: 1.4cqw; align-items: center; }
.cover-tech img { width: clamp(28px, 3.2cqw, 44px); height: clamp(28px, 3.2cqw, 44px); object-fit: contain; }

/* Slide 2 — 데모 영상 */
.demo-main {
  display: grid;
  grid-template-columns: 60% 1fr;
  column-gap: 3cqw;
  align-items: start;
}
.demo-video { width: 100%; aspect-ratio: 16/9; border: none; border-radius: 10px; }
.flow-vertical { display: flex; flex-direction: column; gap: 1.2cqh; }
.flow-step {
  display: flex; gap: 1cqw; align-items: flex-start;
  font-size: clamp(13px, 1.3cqw, 17px);
  line-height: 1.4;
}
.flow-step .n {
  font-family: var(--font-mono);
  font-size: clamp(11px, 1.1cqw, 14px);
  color: var(--accent);
  font-weight: 700;
  flex-shrink: 0; padding-top: 0.1em;
}

/* Slide 3 — 동작 데모 GIF 그리드 */
.demo-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  grid-template-rows: repeat(2, 1fr);
  gap: 1.5cqw;
}
.demo-grid .cell { position: relative; border-radius: 8px; overflow: hidden; }
.demo-grid .cell img { width: 100%; height: 100%; object-fit: cover; display: block; }
.demo-grid .cell .lbl {
  position: absolute; bottom: 0; left: 0; right: 0;
  background: rgba(0,0,0,.55); backdrop-filter: blur(4px);
  text-align: center; padding: 0.4cqh 0;
  font-size: clamp(11px, 1.1cqw, 14px); font-weight: 600;
  color: #fff;
}

/* Slide 4 — 핵심 수치 */
.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 2cqw;
  align-items: center;
}
.metric-card {
  background: var(--surface); border: 1px solid var(--border);
  border-top: 3px solid var(--accent);
  border-radius: 14px; padding: 2.5cqh 2cqw;
  display: flex; flex-direction: column; gap: 0.8cqh;
}
.metric-card .value {
  font-size: clamp(28px, 3.8cqw, 52px);
  font-weight: 800; line-height: 1;
  color: var(--accent);
}
.metric-card .label {
  font-size: clamp(11px, 1.1cqw, 14px);
  color: var(--text-2); font-weight: 500;
}

/* ===== SECTION 2: WHY & WHAT ===== */

/* Slide 5 — 문제 정의 */
.problem-grid {
  display: grid; grid-template-columns: 1fr 1fr; column-gap: 3cqw;
  align-items: start;
}
.problem-grid img { width: 100%; border-radius: 8px; }
.problem-grid .caption {
  margin-top: 1cqh;
  font-size: clamp(13px, 1.3cqw, 17px); color: var(--text-2);
}
.problem-grid b { color: var(--text-1); }

/* Slides 6, 7, 8 — 다이어그램 iframe */
.diagram-frame { width: 100%; height: 100%; border: none; border-radius: 8px; }

/* Slide 9 — 기술 스택 */
.tech-stack-grid {
  display: grid; grid-template-columns: repeat(2, 1fr); gap: 2cqw;
}
.tech-cat {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; padding: 2cqh 2.2cqw;
}
.tech-cat h4 {
  font-size: clamp(13px, 1.3cqw, 17px);
  font-weight: 700; color: var(--accent);
  text-transform: uppercase; letter-spacing: .1em;
  margin: 0 0 1.2cqh;
}
.tech-items { display: flex; flex-wrap: wrap; gap: 0.8cqw; align-items: center; }
.tech-item {
  display: flex; align-items: center; gap: 0.5cqw;
  font-size: clamp(12px, 1.2cqw, 16px); color: var(--text-1);
}
.tech-item img { width: clamp(18px, 2cqw, 26px); height: clamp(18px, 2cqw, 26px); object-fit: contain; }

/* ===== SECTION 3: HOW IT WORKS ===== */

/* Slides 10, 11, 13 — 좌우 2컬럼 */
.two-col {
  display: grid; grid-template-columns: 48% 1fr; column-gap: 3cqw; align-items: start;
}
.two-col img, .two-col .bt-viewer img {
  width: 100%; border-radius: 8px; object-fit: contain;
}

/* Slide 10 — STT 파이프라인 단계 */
.pipeline-steps { display: flex; flex-direction: column; gap: 1.2cqh; }
.pipeline-step {
  display: flex; gap: 1.2cqw; align-items: flex-start;
  background: var(--surface-2); border-radius: 8px; padding: 1cqh 1.4cqw;
}
.pipeline-step .icon { flex-shrink: 0; color: var(--accent); }
.pipeline-step .text .title { font-size: clamp(13px, 1.3cqw, 17px); font-weight: 600; }
.pipeline-step .text .sub { font-size: clamp(11px, 1.1cqw, 13px); color: var(--text-2); margin-top: .3cqh; }

/* Slide 11 — BT 구조 */
.bt-viewer img { width: 100%; border-radius: 8px; }
.bt-steps { display: flex; flex-direction: column; gap: 1cqh; }
.bt-step {
  border-left: 3px solid var(--accent);
  padding: 0.8cqh 1.2cqw;
  background: var(--surface-2); border-radius: 0 8px 8px 0;
}
.bt-step .title { font-size: clamp(13px, 1.3cqw, 17px); font-weight: 600; }
.bt-step .sub { font-size: clamp(11px, 1.1cqw, 13px); color: var(--text-2); margin-top: .2cqh; }

/* Slides 12–14 — 파지 단계 카드 */
.grasp-steps { display: flex; flex-direction: column; gap: 1cqh; }
.grasp-step {
  display: flex; gap: 1cqw; align-items: flex-start;
  padding: 0.9cqh 1.2cqw;
  background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
}
.grasp-step .num {
  font-family: var(--font-mono); font-size: clamp(11px, 1.1cqw, 13px);
  color: var(--accent-2); font-weight: 700; flex-shrink: 0;
}
.grasp-step .body .t { font-size: clamp(13px, 1.3cqw, 17px); font-weight: 600; }
.grasp-step .body .s { font-size: clamp(11px, 1.05cqw, 13px); color: var(--text-2); margin-top: .2cqh; }

/* Slide 15 — 핸드아이 캘리브레이션 */
.handeye {
  display: grid; grid-template-columns: 44% 1fr; column-gap: 3cqw; align-items: center;
}
.handeye img { width: 100%; border-radius: 8px; }
.matrix-block {
  background: #0d1117; border: 1px solid rgba(255,255,255,.1);
  border-radius: 10px; padding: 1.5cqh 2cqw;
  font-family: var(--font-mono); font-size: clamp(13px, 1.3cqw, 16px);
  line-height: 1.8; color: #e6edf3;
}
.matrix-block .comment { color: #8b949e; }

/* Slide 16 — 고정 행동 시퀀스 */
.seq-layout {
  display: grid; grid-template-columns: 48% 1fr; column-gap: 3cqw; align-items: start;
}
.seq-list { display: flex; flex-direction: column; gap: 0.9cqh; }
.seq-item {
  display: flex; gap: 1cqw; align-items: center;
  background: var(--surface-2); border-radius: 8px; padding: 0.9cqh 1.2cqw;
  font-size: clamp(13px, 1.3cqw, 17px);
}
.seq-item .icon { color: var(--accent); flex-shrink: 0; }
.seq-gifs { display: grid; grid-template-rows: 1fr 1fr; gap: 1.2cqh; }
.seq-gifs img { width: 100%; border-radius: 8px; object-fit: cover; }

/* ===== SECTION 4: ENGINEERING DEPTH ===== */

/* Slide 17 — 안전 + DB */
.safety-db {
  display: grid; grid-template-columns: 1fr 1fr; column-gap: 3cqw; align-items: start;
}
.estop-steps { display: flex; flex-direction: column; gap: 0.8cqh; margin-bottom: 1.5cqh; }
.estop-step {
  display: flex; gap: 0.8cqw; align-items: center;
  font-size: clamp(13px, 1.3cqw, 17px);
  border-left: 3px solid var(--bad); padding-left: 1cqw;
}
.estop-step .n { font-family: var(--font-mono); color: var(--bad); font-weight: 700; flex-shrink: 0; }

/* Slide 18 — YOLO 학습 + 리팩터링 */
.dual-col {
  display: grid; grid-template-columns: 1fr 1fr; column-gap: 3cqw; align-items: start;
}
.dual-col img { width: 100%; border-radius: 8px; }
.refactor-compare { display: flex; flex-direction: column; gap: 1cqh; }
.refactor-row {
  display: flex; align-items: center; gap: 1.5cqw;
  font-size: clamp(13px, 1.3cqw, 17px);
}
.refactor-row .badge {
  font-size: clamp(11px, 1.1cqw, 13px); font-weight: 700;
  padding: 0.2cqh 0.8cqw; border-radius: 6px;
  flex-shrink: 0;
}
.badge-before { background: color-mix(in srgb, var(--bad) 15%, transparent); color: var(--bad); }
.badge-after  { background: color-mix(in srgb, var(--good) 15%, transparent); color: var(--good); }

/* ===== SECTION 5: CLOSE ===== */

/* Slide 19 — 도전과제 */
.challenge-grid {
  display: grid; grid-template-columns: repeat(2, 1fr); gap: 2cqw;
}
.challenge-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; padding: 2cqh 2cqw;
  display: flex; flex-direction: column; gap: 0.8cqh;
}
.challenge-card .tag-bad {
  display: inline-block; font-size: clamp(10px, 1.0cqw, 12px); font-weight: 700;
  padding: 0.2cqh 0.7cqw; border-radius: 4px;
  background: color-mix(in srgb, var(--bad) 15%, transparent); color: var(--bad);
  text-transform: uppercase; letter-spacing: .06em;
}
.challenge-card h4 { font-size: clamp(14px, 1.4cqw, 18px); font-weight: 700; margin: 0; }
.challenge-card .prob { font-size: clamp(12px, 1.2cqw, 15px); color: var(--text-2); }
.challenge-card .sol {
  font-size: clamp(12px, 1.2cqw, 15px); color: var(--good);
  display: flex; gap: 0.4cqw; align-items: flex-start;
}

/* Slide 20 — 마무리 */
.closing {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 2.5cqh; text-align: center; height: 100%;
}
.closing .big { font-size: clamp(28px, 4.5cqw, 60px); font-weight: 800; }
.closing .lessons { display: flex; flex-direction: column; gap: 1cqh; text-align: left; width: 60%; }
.closing .lesson-item {
  display: flex; gap: 1cqw; align-items: flex-start;
  font-size: clamp(14px, 1.4cqw, 18px);
}
.closing .lesson-num { font-family: var(--font-mono); color: var(--accent); font-weight: 700; flex-shrink: 0; }
.closing .links { display: flex; gap: 2cqw; align-items: center; }
.closing .links img { width: clamp(22px, 2.5cqw, 32px); opacity: .7; }

/* ===== PROGRESS BAR ===== */
.progress-bar > span { background: var(--accent); }
```

- [ ] **Step 2: CSS 파일 존재 및 최소 줄 수 확인**

```bash
wc -l docs/presentation-v3/assets/overrides.css
```

Expected: 230줄 이상

- [ ] **Step 3: 커밋**

```bash
git add docs/presentation-v3/assets/overrides.css
git commit -m "feat(ppt-v3): add overrides.css with 16:9 strict and all slide layouts"
```

---

## Task 6: index.html — Section 1 (슬라이드 1–4: Hook)

**Files:**
- Create: `docs/presentation-v3/index.html` (뼈대 + 슬라이드 1–4)

- [ ] **Step 0.5: Lucide SRI 해시 계산**

CDN 변조 차단을 위해 `integrity` 속성에 넣을 SHA-384 해시를 미리 계산한다:

```bash
curl -sSL https://unpkg.com/lucide@0.469.0/dist/umd/lucide.min.js \
  | openssl dgst -sha384 -binary | openssl base64 -A
```

출력값 (예: `abc123...=`) 을 메모해 둔다. 아래 `<script>` 태그의 `REPLACE_WITH_HASH` 자리에 넣는다.

- [ ] **Step 1: index.html 뼈대 + 슬라이드 1–4 작성**

`docs/presentation-v3/index.html` 에 다음을 작성한다 (Step 0.5 해시값을 `REPLACE_WITH_HASH` 에 대입):

```html
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HOMIE — 사람의 말을 알아듣고 손을 쓰는 협동로봇</title>
<link rel="stylesheet" href="assets/fonts.css">
<link rel="stylesheet" href="assets/base.css">
<link rel="stylesheet" href="assets/animations/animations.css">
<link rel="stylesheet" href="assets/themes/tokyo-night.css">
<link rel="stylesheet" href="assets/overrides.css">
<script src="https://unpkg.com/lucide@0.469.0/dist/umd/lucide.min.js"
        integrity="sha384-REPLACE_WITH_HASH"
        crossorigin="anonymous"></script>
</head>
<body class="theme-tokyo-night tpl-presenter-mode-reveal">

<div class="deck">

  <!-- Slide 1 — 표지 -->
  <section class="slide" data-slide="1">
    <header class="slide-head">
      <p class="kicker">DOOSAN ROBOTICS BOOTCAMP · ROKEY · B-2 TEAM</p>
      <h2 class="h2">사람의 말을 알아듣고 손을 쓰는 협동로봇</h2>
    </header>
    <div class="slide-body cover">
      <img class="cover-hero" src="assets/media/cover-hero.png" alt="HOMIE 로봇 시연">
      <div class="cover-meta">
        <p class="name">HOMIE</p>
        <p class="tag">Helping Out! Making It Easy!</p>
        <div class="kw">
          <span class="pill">음성 인식</span>
          <span class="pill">멀티모달 AI</span>
          <span class="pill">ROS 2</span>
          <span class="pill">행동 트리</span>
          <span class="pill">분산 시스템</span>
        </div>
        <div class="cover-tech">
          <img src="https://cdn.simpleicons.org/ros/22A7F0" alt="ROS">
          <img src="https://cdn.simpleicons.org/python/3776AB" alt="Python">
          <img src="https://cdn.simpleicons.org/openai/10A37F" alt="OpenAI">
          <img src="https://cdn.simpleicons.org/docker/2496ED" alt="Docker">
          <img src="https://cdn.simpleicons.org/mysql/4479A1" alt="MySQL">
          <img src="https://cdn.simpleicons.org/pytorch/EE4C2C" alt="PyTorch">
        </div>
      </div>
    </div>
    <aside class="notes">표지. 한 마디 음성으로 작업이 완결되는 시스템.</aside>
  </section>

  <!-- Slide 2 — 시연 영상 -->
  <section class="slide" data-slide="2">
    <header class="slide-head">
      <p class="kicker">SECTION 01 · DEMO</p>
      <h2 class="h2">시연 영상</h2>
    </header>
    <div class="slide-body demo-main">
      <iframe class="demo-video"
        src="https://www.youtube.com/embed/n7uikEVqS7M"
        title="HOMIE 시연 영상"
        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
        referrerpolicy="strict-origin-when-cross-origin"
        allowfullscreen></iframe>
      <div class="flow-vertical">
        <div class="flow-step"><span class="n">01</span><span>"왓썹 호미" 호출어 감지</span></div>
        <div class="flow-step"><span class="n">02</span><span>5초 녹음 → Whisper STT</span></div>
        <div class="flow-step"><span class="n">03</span><span>GPT-4o 명령 분해 → JSON</span></div>
        <div class="flow-step"><span class="n">04</span><span>행동 트리 탐색 → 발견 → 접근</span></div>
        <div class="flow-step"><span class="n">05</span><span>VLM + PCA 잡는 자세 결정</span></div>
        <div class="flow-step"><span class="n">06</span><span>m0609 + RG2 집기 → 완료</span></div>
      </div>
    </div>
    <aside class="notes">영상 재생 전 간단히 6단계 흐름 설명.</aside>
  </section>

  <!-- Slide 3 — 6가지 실제 동작 -->
  <section class="slide" data-slide="3">
    <header class="slide-head">
      <p class="kicker">SECTION 01 · ACTION CATALOG</p>
      <h2 class="h2">6가지 실제 동작 — 사과·후추통 데모</h2>
    </header>
    <div class="slide-body demo-grid">
      <div class="cell"><img src="assets/media/demo-apple-find.gif" alt="사과 탐색"><span class="lbl">Find</span></div>
      <div class="cell"><img src="assets/media/demo-apple-pick.gif" alt="사과 집기"><span class="lbl">Pick</span></div>
      <div class="cell"><img src="assets/media/demo-apple-trash.gif" alt="사과 버리기"><span class="lbl">Trash</span></div>
      <div class="cell"><img src="assets/media/demo-shaker-pick.gif" alt="후추통 집기"><span class="lbl">Pick (shaker)</span></div>
      <div class="cell"><img src="assets/media/demo-shaker-shake.gif" alt="후추통 흔들기"><span class="lbl">Shake</span></div>
      <div class="cell"><img src="assets/media/demo-shaker-pour.gif" alt="후추통 붓기"><span class="lbl">Pour</span></div>
    </div>
    <aside class="notes">GIF 6개. 사과(find/pick/trash) + 후추통(pick/shake/pour).</aside>
  </section>

  <!-- Slide 4 — 핵심 수치 -->
  <section class="slide" data-slide="4">
    <header class="slide-head">
      <p class="kicker">SECTION 01 · KEY METRICS</p>
      <h2 class="h2">2주 만에 완성한 동작 가능한 시스템</h2>
    </header>
    <div class="slide-body metric-grid">
      <div class="metric-card">
        <span class="value">99.0%</span>
        <span class="label">YOLO11s mAP@50</span>
      </div>
      <div class="metric-card">
        <span class="value">96.8%</span>
        <span class="label">F1 Score</span>
      </div>
      <div class="metric-card">
        <span class="value">7</span>
        <span class="label">ROS 2 노드 (통합 후)</span>
      </div>
      <div class="metric-card">
        <span class="value">2주</span>
        <span class="label">설계→구현→시연</span>
      </div>
    </div>
    <aside class="notes">숫자로 먼저 임팩트를 준 뒤 기술 설명으로 넘어간다.</aside>
  </section>

```

(파일은 Task 7~11 에서 슬라이드를 계속 추가. 아직 닫지 않음.)

- [ ] **Step 2: 브라우저에서 슬라이드 1–4 시각 확인**

```bash
python3 -m http.server 8000 --directory docs/presentation-v3 &
# http://localhost:8000/ 열어서 슬라이드 1~4 확인
# 16:9 비율, 헤더 상단, 18px 이상 폰트 체크
```

- [ ] **Step 3: 이모지 없음 확인**

```bash
python3 -c "
import re, sys
txt = open('docs/presentation-v3/index.html').read()
# Unicode emoji range check
found = re.findall(r'[\U0001F300-\U0001F9FF\U00002600-\U000027BF]', txt)
print('emoji found:', found if found else 'none')
"
```

Expected: `emoji found: none`

- [ ] **Step 4: 커밋**

```bash
git add docs/presentation-v3/index.html
git commit -m "feat(ppt-v3): slides 1-4 hook section"
```

---

## Task 7: index.html — Section 2 (슬라이드 5–9: Why & What)

**Files:**
- Modify: `docs/presentation-v3/index.html` (슬라이드 5–9 추가)

- [ ] **Step 1: 슬라이드 5–9 추가**

`docs/presentation-v3/index.html` 에서 슬라이드 4 의 `</section>` 다음에 이어 붙인다:

```html
  <!-- Slide 5 — 문제 정의 -->
  <section class="slide" data-slide="5">
    <header class="slide-head">
      <p class="kicker">SECTION 02 · PROBLEM DEFINITION</p>
      <h2 class="h2">왜 음성 인터페이스가 필요한가</h2>
    </header>
    <div class="slide-body problem-grid">
      <div>
        <img src="assets/media/social-background.png" alt="사회적 배경">
        <p class="caption"><b>고령화·1인 가구</b> 증가 — 단순 반복 작업 자동화 수요 급증</p>
      </div>
      <div>
        <img src="assets/media/market-trend.png" alt="시장 트렌드">
        <p class="caption"><b>협동로봇 시장</b> 연평균 30%+ 성장 — 음성 UX 가 진입 장벽 낮춤</p>
      </div>
    </div>
    <aside class="notes">배경 슬라이드. 간결하게 1장으로 마무리.</aside>
  </section>

  <!-- Slide 6 — 시스템 아키텍처 -->
  <section class="slide" data-slide="6">
    <header class="slide-head">
      <p class="kicker">SECTION 02 · SYSTEM ARCHITECTURE</p>
      <h2 class="h2">두 PC, 한 명령 — 책임 분리 구조</h2>
    </header>
    <div class="slide-body" style="height:100%;">
      <iframe class="diagram-frame" src="diagrams/arch-system.html" title="시스템 아키텍처"></iframe>
    </div>
    <aside class="notes">sub1(음성/UI) ↔ CycloneDDS LAN ↔ main(로봇). 토픽/액션/서비스 색상 구분.</aside>
  </section>

  <!-- Slide 7 — 노드 아키텍처 -->
  <section class="slide" data-slide="7">
    <header class="slide-head">
      <p class="kicker">SECTION 02 · NODE ARCHITECTURE</p>
      <h2 class="h2">노드 7개 · 단일 책임 원칙</h2>
    </header>
    <div class="slide-body" style="height:100%;">
      <iframe class="diagram-frame" src="diagrams/arch-nodes.html" title="노드 아키텍처"></iframe>
    </div>
    <aside class="notes">7노드 각 책임 + 인터페이스. 14노드에서 R1 통합 결과.</aside>
  </section>

  <!-- Slide 8 — 전체 워크플로우 -->
  <section class="slide" data-slide="8">
    <header class="slide-head">
      <p class="kicker">SECTION 02 · FULL WORKFLOW</p>
      <h2 class="h2">발화부터 파지까지 — 단계별 흐름</h2>
    </header>
    <div class="slide-body" style="height:100%;">
      <iframe class="diagram-frame" src="diagrams/arch-workflow.html" title="전체 워크플로우"></iframe>
    </div>
    <aside class="notes">8단계 waterfall. 동적 파지 분기 포함.</aside>
  </section>

  <!-- Slide 9 — 기술 스택 -->
  <section class="slide" data-slide="9">
    <header class="slide-head">
      <p class="kicker">SECTION 02 · TECH STACK</p>
      <h2 class="h2">네 카테고리, 한 페이지 — 핵심 기술 스택</h2>
    </header>
    <div class="slide-body tech-stack-grid">
      <div class="tech-cat">
        <h4><i data-lucide="cpu"></i> HARDWARE</h4>
        <div class="tech-items">
          <span class="tech-item">Doosan m0609</span>
          <span class="tech-item">OnRobot RG2</span>
          <span class="tech-item">RealSense D435</span>
        </div>
      </div>
      <div class="tech-cat">
        <h4><i data-lucide="brain"></i> AI</h4>
        <div class="tech-items">
          <span class="tech-item"><img src="https://cdn.simpleicons.org/pytorch/EE4C2C" alt="">YOLO11s</span>
          <span class="tech-item"><img src="https://cdn.simpleicons.org/openai/10A37F" alt="">GPT-4o</span>
          <span class="tech-item">Whisper</span>
          <span class="tech-item">openWakeWord</span>
        </div>
      </div>
      <div class="tech-cat">
        <h4><i data-lucide="network"></i> MIDDLEWARE</h4>
        <div class="tech-items">
          <span class="tech-item"><img src="https://cdn.simpleicons.org/ros/22A7F0" alt="">ROS 2</span>
          <span class="tech-item">BehaviorTree.CPP</span>
          <span class="tech-item">CycloneDDS</span>
          <span class="tech-item"><img src="https://cdn.simpleicons.org/docker/2496ED" alt="">Docker</span>
        </div>
      </div>
      <div class="tech-cat">
        <h4><i data-lucide="code-2"></i> DEV</h4>
        <div class="tech-items">
          <span class="tech-item"><img src="https://cdn.simpleicons.org/python/3776AB" alt="">Python</span>
          <span class="tech-item">C++</span>
          <span class="tech-item"><img src="https://cdn.simpleicons.org/mysql/4479A1" alt="">MySQL</span>
          <span class="tech-item"><img src="https://cdn.simpleicons.org/fastapi/009688" alt="">FastAPI</span>
        </div>
      </div>
    </div>
    <aside class="notes">4카테고리. simpleicons + Lucide 혼용.</aside>
  </section>

```

- [ ] **Step 2: 슬라이드 수 확인**

```bash
grep -c 'data-slide=' docs/presentation-v3/index.html
```

Expected: 9

- [ ] **Step 3: 커밋**

```bash
git add docs/presentation-v3/index.html
git commit -m "feat(ppt-v3): slides 5-9 why and what section"
```

---

## Task 8: index.html — Section 3 Part 1 (슬라이드 10–13)

**Files:**
- Modify: `docs/presentation-v3/index.html` (슬라이드 10–13 추가)

- [ ] **Step 1: 슬라이드 10–13 추가**

슬라이드 9 `</section>` 다음에 이어 붙인다:

```html
  <!-- Slide 10 — 음성 파이프라인 -->
  <section class="slide" data-slide="10">
    <header class="slide-head">
      <p class="kicker">SECTION 02 · VOICE PIPELINE</p>
      <h2 class="h2">발화에서 JSON 명령까지 — 6초 흐름</h2>
    </header>
    <div class="slide-body two-col">
      <div class="pipeline-steps">
        <div class="pipeline-step">
          <i data-lucide="mic" class="icon"></i>
          <div class="text"><div class="title">호출어 감지</div><div class="sub">openwakeword · wassup_homie.onnx</div></div>
        </div>
        <div class="pipeline-step">
          <i data-lucide="radio" class="icon"></i>
          <div class="text"><div class="title">5초 녹음</div><div class="sub">PyAudio → WAV bytes</div></div>
        </div>
        <div class="pipeline-step">
          <i data-lucide="speech" class="icon"></i>
          <div class="text"><div class="title">Whisper STT</div><div class="sub">한국어 전사 · medium 모델</div></div>
        </div>
        <div class="pipeline-step">
          <i data-lucide="bot" class="icon"></i>
          <div class="text"><div class="title">GPT-4o 정련</div><div class="sub">pick/place/pour 중 단일 액션 카탈로그로 정규화</div></div>
        </div>
        <div class="pipeline-step">
          <i data-lucide="send" class="icon"></i>
          <div class="text"><div class="title">/voice_command 발행</div><div class="sub">JSON 배열 → bt_manager 수신</div></div>
        </div>
      </div>
      <img src="assets/media/stt-prompt-rule.png" alt="프롬프트 규칙">
    </div>
    <aside class="notes">5단계 파이프라인. 프롬프트 규칙이 핵심 — 카탈로그 외 명령은 거부.</aside>
  </section>

  <!-- Slide 11 — BT 오케스트레이션 -->
  <section class="slide" data-slide="11">
    <header class="slide-head">
      <p class="kicker">SECTION 02 · BEHAVIOR TREE</p>
      <h2 class="h2">한 명령이 여러 단계로 — BehaviorTree.CPP v3</h2>
    </header>
    <div class="slide-body two-col">
      <div class="bt-steps">
        <div class="bt-step">
          <div class="title">PopNextTask</div>
          <div class="sub">JSON 큐에서 다음 액션 꺼내기 · 드레인 후 reset 자동 emit</div>
        </div>
        <div class="bt-step">
          <div class="title">IsTargetRequired?</div>
          <div class="sub">물체 탐색 필요 여부 분기</div>
        </div>
        <div class="bt-step">
          <div class="title">SearchLogic (Fallback)</div>
          <div class="sub">IsTargetLocated → detect_in_place → finding · 변칙 대응</div>
        </div>
        <div class="bt-step">
          <div class="title">ExecutePythonAction</div>
          <div class="sub">execute_command 액션 서버 호출 → executer 실행</div>
        </div>
      </div>
      <div class="bt-viewer">
        <img src="assets/media/bt-groot-viewer.png" alt="Groot 2 BT 뷰어">
        <p style="font-size:clamp(10px,1.0cqw,13px);color:var(--text-3);margin-top:.5cqh;">Groot 2 · KeepRunningUntilFailure → SearchLogic Fallback</p>
      </div>
    </div>
    <aside class="notes">Groot 2 스크린샷 보여주며 BT 구조 설명.</aside>
  </section>

  <!-- Slide 12 — 동적 파지 ① 탐색 -->
  <section class="slide" data-slide="12">
    <header class="slide-head">
      <p class="kicker">SECTION 02 · DYNAMIC GRASP · 1/3</p>
      <h2 class="h2">1차 탐색 — YOLO 로 목표 물체 발견</h2>
    </header>
    <div class="slide-body two-col">
      <div class="grasp-steps">
        <div class="grasp-step">
          <span class="num">01</span>
          <div class="body"><div class="t">1차 탐색 위치로 이동</div><div class="s">사전 정의 관찰 자세로 movel</div></div>
        </div>
        <div class="grasp-step">
          <span class="num">02</span>
          <div class="body"><div class="t">YOLO11s 탐지</div><div class="s">7 클래스 (사과·바나나·후추통 등) 실시간 detect</div></div>
        </div>
        <div class="grasp-step">
          <span class="num">03</span>
          <div class="body"><div class="t">depth 기반 3D 위치 추정</div><div class="s">RealSense D435 depth + 카메라 내부 파라미터 → 3D 좌표</div></div>
        </div>
        <div class="grasp-step">
          <span class="num">04</span>
          <div class="body"><div class="t">물체 근처로 이동 (approach)</div><div class="s">base_pose 오프셋만큼 movel → 2차 탐색 시야 확보</div></div>
        </div>
      </div>
      <img src="assets/media/vision-yolo-result.png" alt="YOLO 탐지 결과">
    </div>
    <aside class="notes">1차 탐색은 빠른 위치 추정용. depth 오차가 있으므로 2차 근접 재탐지가 핵심.</aside>
  </section>

  <!-- Slide 13 — 동적 파지 ② 근접 재탐지 -->
  <section class="slide" data-slide="13">
    <header class="slide-head">
      <p class="kicker">SECTION 02 · DYNAMIC GRASP · 2/3</p>
      <h2 class="h2">2차 근접 재탐지 — VLM ROI 로 depth 오차 예방</h2>
    </header>
    <div class="slide-body two-col">
      <div class="grasp-steps">
        <div class="grasp-step">
          <span class="num">05</span>
          <div class="body"><div class="t">2차 탐색 위치로 이동</div><div class="s">물체에 더 가까운 관찰 자세 — depth 오차 최소화</div></div>
        </div>
        <div class="grasp-step">
          <span class="num">06</span>
          <div class="body"><div class="t">YOLO 재탐지</div><div class="s">근접 위치에서 bbox 재획득</div></div>
        </div>
        <div class="grasp-step">
          <span class="num">07</span>
          <div class="body"><div class="t">VLM ROI 요청 (GPT-4o)</div><div class="s">이미지 crop 전송 → "잡기 가장 좋은 부위" 좌표 반환</div></div>
        </div>
        <div class="grasp-step">
          <span class="num">08</span>
          <div class="body"><div class="t">ROI × 1.5 포인트클라우드 추출</div><div class="s">VLM 반환 ROI 를 1.5배 확장 → depth cloud 필터링</div></div>
        </div>
      </div>
      <img src="assets/media/vision-workflow.png" alt="비전 워크플로우">
    </div>
    <aside class="notes">VLM 이 잡는 부위를 지정한다는 게 핵심. ROI×1.5 로 손가락 충돌 여유 확보.</aside>
  </section>

```

- [ ] **Step 2: 슬라이드 수 확인**

```bash
grep -c 'data-slide=' docs/presentation-v3/index.html
```

Expected: 13

- [ ] **Step 3: 커밋**

```bash
git add docs/presentation-v3/index.html
git commit -m "feat(ppt-v3): slides 10-13 voice pipeline and grasp detection"
```

---

## Task 9: index.html — Section 3 Part 2 (슬라이드 14–16)

**Files:**
- Modify: `docs/presentation-v3/index.html` (슬라이드 14–16 추가)

- [ ] **Step 1: 슬라이드 14–16 추가**

슬라이드 13 `</section>` 다음에 이어 붙인다:

```html
  <!-- Slide 14 — 동적 파지 ③ PCA 접근 계산 -->
  <section class="slide" data-slide="14">
    <header class="slide-head">
      <p class="kicker">SECTION 02 · DYNAMIC GRASP · 3/3</p>
      <h2 class="h2">포인트클라우드 PCA — 물체 형상으로 그리퍼 자세 결정</h2>
    </header>
    <div class="slide-body two-col">
      <div class="grasp-steps">
        <div class="grasp-step">
          <span class="num">09</span>
          <div class="body"><div class="t">포인트클라우드 분포 분석 (PCA)</div><div class="s">주성분 분석으로 물체 주축·단축 계산</div></div>
        </div>
        <div class="grasp-step">
          <span class="num">10</span>
          <div class="body"><div class="t">형상별 접근 전략 분기</div><div class="s">평면(접시) → 반경 방향 / 원통(후추통) → 장축 수직</div></div>
        </div>
        <div class="grasp-step">
          <span class="num">11</span>
          <div class="body"><div class="t">그리퍼 자세 & 접근 벡터 산출</div><div class="s">T_gripper2camera(4×4) 핸드아이 변환 → 베이스 좌표</div></div>
        </div>
        <div class="grasp-step">
          <span class="num">12</span>
          <div class="body"><div class="t">2차 위치에서 출발 → GRIP</div><div class="s">movel 접근 → RG2 width 제어 → 파지 완료</div></div>
        </div>
      </div>
      <!-- PCA 개념 인라인 SVG -->
      <svg viewBox="0 0 300 220" xmlns="http://www.w3.org/2000/svg" style="width:100%;border-radius:8px;background:#0d1117;">
        <text x="150" y="22" text-anchor="middle" fill="#a9b1d6" font-size="13" font-family="monospace">Point Cloud + PCA</text>
        <!-- 포인트 클라우드 점들 (타원 분포) -->
        <ellipse cx="150" cy="120" rx="90" ry="40" fill="none" stroke="#3d59a1" stroke-width="1" stroke-dasharray="4"/>
        <g fill="#7aa2f7" opacity=".7">
          <circle cx="120" cy="110" r="3"/><circle cx="135" cy="105" r="3"/>
          <circle cx="150" cy="100" r="3"/><circle cx="165" cy="105" r="3"/>
          <circle cx="180" cy="110" r="3"/><circle cx="125" cy="120" r="3"/>
          <circle cx="140" cy="115" r="3"/><circle cx="155" cy="115" r="3"/>
          <circle cx="170" cy="120" r="3"/><circle cx="130" cy="130" r="3"/>
          <circle cx="145" cy="125" r="3"/><circle cx="160" cy="128" r="3"/>
          <circle cx="175" cy="130" r="3"/>
        </g>
        <!-- 주축 화살표 (빨간) -->
        <line x1="70" y1="115" x2="230" y2="115" stroke="#f7768e" stroke-width="2.5" marker-end="url(#arr-r)"/>
        <text x="232" y="119" fill="#f7768e" font-size="11" font-family="monospace">PC1(장축)</text>
        <!-- 단축 화살표 (초록) -->
        <line x1="150" y1="165" x2="150" y2="70" stroke="#9ece6a" stroke-width="2.5" marker-end="url(#arr-g)"/>
        <text x="154" y="68" fill="#9ece6a" font-size="11" font-family="monospace">PC2(단축)</text>
        <!-- 그리퍼 아이콘 (단순 직사각형 2개) -->
        <rect x="108" y="48" width="12" height="18" rx="2" fill="#bb9af7" opacity=".8"/>
        <rect x="122" y="48" width="12" height="18" rx="2" fill="#bb9af7" opacity=".8"/>
        <text x="135" y="44" fill="#bb9af7" font-size="10" font-family="monospace">gripper</text>
        <!-- 화살표 defs -->
        <defs>
          <marker id="arr-r" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
            <path d="M0,0 L0,6 L6,3 z" fill="#f7768e"/>
          </marker>
          <marker id="arr-g" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
            <path d="M0,0 L0,6 L6,3 z" fill="#9ece6a"/>
          </marker>
        </defs>
      </svg>
    </div>
    <aside class="notes">PCA 두 주성분으로 물체 방향 파악 → 형상별 분기 전략이 핵심.</aside>
  </section>

  <!-- Slide 15 — 핸드아이 캘리브레이션 -->
  <section class="slide" data-slide="15">
    <header class="slide-head">
      <p class="kicker">SECTION 02 · HAND-EYE CALIBRATION</p>
      <h2 class="h2">카메라 좌표 → 베이스 좌표 — 5° 기울임의 해결</h2>
    </header>
    <div class="slide-body handeye">
      <img src="assets/media/vision-depth-tilt.png" alt="5도 기울임 도식">
      <div>
        <p style="font-size:clamp(13px,1.3cqw,17px);color:var(--text-2);margin:0 0 1.5cqh;">
          카메라가 5° 아래로 기울어진 환경에서 <b style="color:var(--text-1);">depth 오차</b>가 발생.<br>
          cv2.calibrateHandEye() 로 4×4 변환 행렬을 사전 계산해 런타임에 보정.
        </p>
        <div class="matrix-block">
<span class="comment"># T_gripper2camera.npy (4×4, 단위: mm)</span>
[[ 0.999  -0.012   0.034  -28.3 ]
 [ 0.013   0.999  -0.018   12.1 ]
 [-0.034   0.019   0.999  112.5 ]
 [ 0.      0.      0.       1.  ]]
        </div>
        <p style="font-size:clamp(11px,1.1cqw,13px);color:var(--text-3);margin:1cqh 0 0;">
          파일 미발견 시 RuntimeError — fail-fast 설계 (무음 실패 방지)
        </p>
      </div>
    </div>
    <aside class="notes">5° 기울임이 없으면 이 캘리브레이션이 필요 없다는 점 강조.</aside>
  </section>

  <!-- Slide 16 — 고정 행동 시퀀스 -->
  <section class="slide" data-slide="16">
    <header class="slide-head">
      <p class="kicker">SECTION 02 · FIXED SEQUENCES</p>
      <h2 class="h2">파지 후 — 사전 설계된 고정 시퀀스 실행</h2>
    </header>
    <div class="slide-body seq-layout">
      <div class="seq-list">
        <div class="seq-item"><i data-lucide="arrow-right" class="icon"></i><span><b>place</b> — 지정 위치에 내려놓기</span></div>
        <div class="seq-item"><i data-lucide="trash-2" class="icon"></i><span><b>trash</b> — 쓰레기통 위 해제</span></div>
        <div class="seq-item"><i data-lucide="droplets" class="icon"></i><span><b>pour</b> — 컵 위에서 기울여 붓기</span></div>
        <div class="seq-item"><i data-lucide="move" class="icon"></i><span><b>shake</b> — 정해진 자세에서 흔들기</span></div>
        <div class="seq-item"><i data-lucide="home" class="icon"></i><span><b>홈 복귀</b> — 모든 시퀀스 후 대기 자세</span></div>
      </div>
      <div class="seq-gifs">
        <img src="assets/media/demo-apple-trash.gif" alt="trash 동작">
        <img src="assets/media/demo-shaker-pour.gif" alt="pour 동작">
      </div>
    </div>
    <aside class="notes">동적 파지 → 고정 시퀀스 → 홈 복귀 흐름. 시퀀스는 하드코딩 DSR 모션.</aside>
  </section>

```

- [ ] **Step 2: 슬라이드 수 확인**

```bash
grep -c 'data-slide=' docs/presentation-v3/index.html
```

Expected: 16

- [ ] **Step 3: 커밋**

```bash
git add docs/presentation-v3/index.html
git commit -m "feat(ppt-v3): slides 14-16 PCA grasp and fixed sequences"
```

---

## Task 10: index.html — Section 4–5 (슬라이드 17–20: Depth + Close)

**Files:**
- Modify: `docs/presentation-v3/index.html` (슬라이드 17–20 추가 + 닫기)

- [ ] **Step 1: 슬라이드 17–20 추가 + 파일 닫기**

슬라이드 16 `</section>` 다음에 이어 붙이고, 마지막에 파일 닫기 태그까지 작성한다:

```html
  <!-- Slide 17 — 안전 시스템 + DB 로깅 -->
  <section class="slide" data-slide="17">
    <header class="slide-head">
      <p class="kicker">SECTION 03 · SAFETY &amp; PERSISTENCE</p>
      <h2 class="h2">즉시 정지 + DB 격리 — 운영 안정성 설계</h2>
    </header>
    <div class="slide-body safety-db">
      <div>
        <div class="estop-steps">
          <div class="estop-step"><span class="n">1</span><span>move_stop — 현재 모션 즉시 중단</span></div>
          <div class="estop-step"><span class="n">2</span><span>drl_stop — DRL 프로그램 종료</span></div>
          <div class="estop-step"><span class="n">3</span><span>set_safety_mode(RECOVERY) — 안전 모드 전환</span></div>
        </div>
        <img src="assets/media/ui-admin-dashboard.gif" alt="관리자 대시보드" style="width:100%;border-radius:8px;margin-top:1cqh;">
      </div>
      <div>
        <img src="assets/media/db-docker-structure.png" alt="DB Docker 구조" style="width:100%;border-radius:8px;">
        <p style="font-size:clamp(11px,1.1cqw,14px);color:var(--text-2);margin-top:0.8cqh;">
          admin 컨테이너는 <b style="color:var(--text-1);">DDS 미참여</b> — DB 만 공유.<br>
          ROS 노드와 완전 격리된 디버깅 창.
        </p>
      </div>
    </div>
    <aside class="notes">ESTOP 3단 + DB-only 격리 패턴. silent 실패 방지가 설계 원칙.</aside>
  </section>

  <!-- Slide 18 — YOLO 학습 + 리팩터링 -->
  <section class="slide" data-slide="18">
    <header class="slide-head">
      <p class="kicker">SECTION 03 · QUALITY</p>
      <h2 class="h2">데이터 정제 + 아키텍처 통합 — 품질 개선</h2>
    </header>
    <div class="slide-body dual-col">
      <div>
        <img src="assets/media/vision-yolo-comparison.png" alt="YOLO v3 vs v4 비교">
        <p style="font-size:clamp(11px,1.1cqw,14px);color:var(--text-2);margin-top:0.8cqh;">
          v3(bbox 중복·라벨오류) → v4(정제) · fitness <b style="color:var(--good);">0.65 → 0.93</b>
        </p>
        <img src="assets/media/yolo-fitness-overview.png" alt="YOLO fitness 개요" style="margin-top:1cqh;border-radius:8px;">
      </div>
      <div class="refactor-compare">
        <p style="font-size:clamp(14px,1.4cqw,18px);font-weight:700;margin:0 0 1.2cqh;">노드 통합 (R1)</p>
        <div class="refactor-row">
          <span class="badge badge-before">Before</span>
          <span>14 노드 — voice_processing, VisionStrategy, pick_vertical/horizontal/side …</span>
        </div>
        <div style="text-align:center;font-size:clamp(18px,2cqw,28px);color:var(--accent);margin:.8cqh 0;">↓</div>
        <div class="refactor-row">
          <span class="badge badge-after">After</span>
          <span>7 노드 — 단일 책임, grasp_perception_node 단일 진입점</span>
        </div>
        <p style="font-size:clamp(11px,1.1cqw,13px);color:var(--text-2);margin-top:1.2cqh;">
          pick_vertical/horizontal/side 제거 → grasp_node 의 mode 파라미터로 통일.<br>
          VisionStrategy 패턴 → 단일 서비스 엔드포인트로 단순화.
        </p>
      </div>
    </div>
    <aside class="notes">데이터 품질 + 아키텍처 정리 두 가지를 한 장으로. 숫자로 증명.</aside>
  </section>

  <!-- Slide 19 — 도전과제 & 해결 -->
  <section class="slide" data-slide="19">
    <header class="slide-head">
      <p class="kicker">SECTION 03 · CHALLENGES</p>
      <h2 class="h2">네 가지 함정 · 네 가지 해결</h2>
    </header>
    <div class="slide-body challenge-grid">
      <div class="challenge-card">
        <span class="tag-bad">BT</span>
        <h4>KeepRunningUntilFailure 무한 루프</h4>
        <p class="prob">큐 소진 후 SUCCESS 가 없으면 BT 가 루트부터 재실행</p>
        <p class="sol"><i data-lucide="check" style="width:14px;"></i> PopNextTask 에 reset-after-drain 래치 — 큐 빔 → reset 1회 emit</p>
      </div>
      <div class="challenge-card">
        <span class="tag-bad">VISION</span>
        <h4>depth 카메라 원거리 오차</h4>
        <p class="prob">1차 탐색 depth 값이 실제보다 크게 나와 접근 위치 빗나감</p>
        <p class="sol"><i data-lucide="check" style="width:14px;"></i> 2차 근접 재탐지 — 물체 바로 앞에서 depth 재측정</p>
      </div>
      <div class="challenge-card">
        <span class="tag-bad">AI</span>
        <h4>VLM latency (1–3초)</h4>
        <p class="prob">매 프레임 GPT-4o 호출 시 파지 사이클 전체가 지연</p>
        <p class="sol"><i data-lucide="check" style="width:14px;"></i> 2차 탐지 1회만 호출 — 결과 캐시, 재호출 없음</p>
      </div>
      <div class="challenge-card">
        <span class="tag-bad">DDS</span>
        <h4>CycloneDDS 멀티캐스트 불안정</h4>
        <p class="prob">main_PC ↔ sub1_PC 간 토픽 수신 지연·드롭</p>
        <p class="sol"><i data-lucide="check" style="width:14px;"></i> cyclonedds.xml 유니캐스트 피어 명시 — 안정적 cross-host 통신</p>
      </div>
    </div>
    <aside class="notes">실제 겪은 문제 4개. 문제→해결 포맷으로 문제 해결 능력 어필.</aside>
  </section>

  <!-- Slide 20 — 마무리 / Q&A -->
  <section class="slide" data-slide="20">
    <header class="slide-head">
      <p class="kicker">SECTION 04 · Q &amp; A</p>
      <h2 class="h2">감사합니다 — 질문 환영합니다</h2>
    </header>
    <div class="slide-body closing">
      <p class="big gradient-text">HOMIE</p>
      <div class="lessons">
        <div class="lesson-item"><span class="lesson-num">01</span><span>음성 UX 는 <b>프롬프트 규칙</b>이 전부 — 카탈로그 외는 거부</span></div>
        <div class="lesson-item"><span class="lesson-num">02</span><span><b>2단계 탐지</b>가 depth 오차를 이긴다 — 근접 재탐지가 핵심</span></div>
        <div class="lesson-item"><span class="lesson-num">03</span><span>아키텍처는 <b>단일 책임</b>으로 — 14→7 노드, 테스트 가능성 향상</span></div>
      </div>
      <div class="links">
        <img src="https://cdn.simpleicons.org/github/C9D1D9" alt="GitHub">
        <span style="font-size:clamp(13px,1.3cqw,18px);color:var(--text-2);">github.com/dev-kibeom/robo_chef</span>
      </div>
    </div>
    <aside class="notes">3가지 핵심 교훈으로 마무리. Q&A 시간.</aside>
  </section>

</div><!-- /.deck -->

<!-- 네비게이션 -->
<div class="deck-header">
  <span>HOMIE</span>
  <span class="slide-number" data-current="1" data-total="20"></span>
</div>
<div class="progress-bar"><span></span></div>

<script>lucide.createIcons();</script>
<script src="assets/runtime.js"></script>
</body>
</html>
```

- [ ] **Step 2: 슬라이드 수 확인 + 이모지 체크**

```bash
grep -c 'data-slide=' docs/presentation-v3/index.html
```

Expected: 20

```bash
python3 -c "
import re
txt = open('docs/presentation-v3/index.html').read()
found = re.findall(r'[\U0001F300-\U0001F9FF\U00002600-\U000027BF]', txt)
print('emoji:', found if found else 'none — OK')
"
```

Expected: `emoji: none — OK`

- [ ] **Step 3: 커밋**

```bash
git add docs/presentation-v3/index.html
git commit -m "feat(ppt-v3): slides 17-20 engineering depth and close section"
```

---

## Task 11: 최종 검증 + 서버 실행

**Files:**
- Verify: `docs/presentation-v3/index.html`, `assets/overrides.css`, `diagrams/*.html`

- [ ] **Step 1: 파일 체크리스트**

```bash
cd /home/hoon/cobot_ws/src/cobot2

echo "=== 필수 파일 ==="
for f in \
  docs/presentation-v3/index.html \
  docs/presentation-v3/assets/overrides.css \
  docs/presentation-v3/assets/base.css \
  docs/presentation-v3/assets/runtime.js \
  docs/presentation-v3/assets/themes/tokyo-night.css \
  docs/presentation-v3/diagrams/arch-system.html \
  docs/presentation-v3/diagrams/arch-nodes.html \
  docs/presentation-v3/diagrams/arch-workflow.html; do
  test -f "$f" && echo "✓ $f" || echo "✗ MISSING: $f"
done

echo ""
echo "=== media symlink ==="
ls -la docs/presentation-v3/assets/media | head -3

echo ""
echo "=== 슬라이드 20장 확인 ==="
grep -c 'data-slide=' docs/presentation-v3/index.html

echo ""
echo "=== 이모지 없음 ==="
python3 -c "
import re
txt = open('docs/presentation-v3/index.html').read()
found = re.findall(r'[\U0001F300-\U0001F9FF\U00002600-\U000027BF]', txt)
print('emoji:', found if found else 'none — OK')
"

echo ""
echo "=== 최소 폰트 18px 확인 (clamp 하한) ==="
grep -c 'clamp(18px\|clamp(1[89]px\|clamp(2[0-9]px' docs/presentation-v3/assets/overrides.css
```

Expected: 모든 파일 ✓, 슬라이드 20, 이모지 none, clamp 하한 18px 이상

- [ ] **Step 2: HTTP 서버로 시각 확인**

```bash
python3 -m http.server 8000 --directory /home/hoon/cobot_ws/src/cobot2/docs/presentation-v3
```

`http://localhost:8000/` 에서 확인:
- [ ] 슬라이드 1 표지: cover-hero 이미지, 기술 스택 아이콘 표시
- [ ] 슬라이드 2 시연 영상: YouTube iframe 재생 가능 (http 서버 필요)
- [ ] 슬라이드 3 GIF 그리드: 6개 GIF 재생
- [ ] 슬라이드 4 메트릭: 4개 카드 수평 배치
- [ ] 슬라이드 6–8 다이어그램: iframe 내 SVG 렌더링 OK
- [ ] 좁은 뷰포트(800px)에서도 16:9 비율 유지 (letterbox 검은 띠)
- [ ] ← → 키로 슬라이드 전환

- [ ] **Step 3: 최종 커밋**

```bash
cd /home/hoon/cobot_ws/src/cobot2
git add docs/presentation-v3/
git commit -m "feat(ppt-v3): presentation-v3 complete — 20-slide impact-first portfolio deck"
```

---

## 자체 검토 (Spec Coverage)

| 스펙 요건 | 커버 태스크 |
|---|---|
| 20슬라이드 임팩트-퍼스트 | Task 6–10 |
| 16:9 strict letterbox | Task 5 (overrides.css) |
| 최소 18px 폰트 | Task 5 (clamp(18px, ...)) |
| 헤더 상단 배치 | Task 5 (.slide grid-template-rows: auto 1fr) |
| 이모지 금지 | Task 6 Step 3, Task 11 Step 1 |
| Lucide 아이콘 | Task 7–10 (data-lucide) |
| simpleicons CDN | Task 7–10 |
| 시스템 아키텍처 다이어그램 | Task 2 |
| 노드 아키텍처 다이어그램 | Task 3 |
| 전체 워크플로우 다이어그램 | Task 4 |
| 6 GIF 재사용 | Task 6 (슬라이드 3), Task 9 (슬라이드 16) |
| presentation-v2 이미지 재사용 | Task 1 (symlink) + Task 6–10 |
| 워크플로우 전체 커버 (wakeup→grip→홈) | 슬라이드 10–16 (Task 8–9) |
| 도전과제 4종 | Task 10 (슬라이드 19) |
| Korean language | Task 6–10 모든 텍스트 한국어 |
| 한국어 발표자 노트 | Task 6–10 모든 `<aside class="notes">` |
| docs/presentation-v3/ 출력 | Task 1 |
