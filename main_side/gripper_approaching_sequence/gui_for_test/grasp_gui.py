"""grasp_gui.py — 클릭 기반 Semantic Grasp 테스트 GUI.

흐름:
  1) 라이브 뷰에 YOLO bbox 가 실시간 그려짐
  2) bbox 위 좌클릭 → 해당 객체 crop 이 우측 ① 패널에 고정
  3) 자동으로 OpenAI VLM 호출 → grasp ROI 수신, ② 패널에 표시
  4) BBox 영역(법선 추정용) + ROI 영역(위치 산출용) depth 분리 추출
  5) PCA → grasp pose: tilt/azimuth/principal-yaw + planarity/linearity 계산
  6) ② 패널에 approach 화살표(노랑) + principal axis(시안) + tilt 각도 라벨
     ④ 패널에 모든 수치 (스크롤 가능)
     ③ 패널에 jet heatmap (필터 통과 영역 흰선)
  7) 매 단계 이미지를 history_images/{ts}_{class}/ 에 자동 저장
  8) 하단 로그: 프롬프트, eigvals, 각도, 신뢰도 등 상세 출력

사용:
  source /home/rokey/cobot_ws/install/setup.bash
  python3 /home/rokey/cobot_ws/src/donttouch/gripper_approaching_sequence/gui_for_test/grasp_gui.py
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from PIL import Image as PILImage, ImageTk

import rclpy
from rclpy.executors import SingleThreadedExecutor

_PKG_ROOT = Path(__file__).resolve().parents[1]
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from gripper_approaching_sequence.perception import (
    ImgNode, YoloDetector, Detection, crop_bbox, wait_for_frames,
)
from gripper_approaching_sequence.vlm_client import (
    VLMClient, GraspROI, to_global_bbox, make_grasp_prompt,
)
from gripper_approaching_sequence.grasp_geometry import (
    filter_depth_roi, deproject_mask, compute_grasp_pose,
    estimate_workbench_plane, perpendicular_distance,
    GraspPose, project_to_image,
)
from gripper_approaching_sequence.motion import (
    cam_pose_to_base_pose, get_robot_pose_matrix, load_handeye_matrix,
    DoosanGripperMotion, setup_dsr,
)


# ── 디스플레이 / 저장 상수 ────────────────────
LIVE_W, LIVE_H = 800, 600
THUMB_W, THUMB_H = 440, 310
TICK_MS = 50
LOG_DRAIN_MS = 100
RESULT_DRAIN_MS = 50

HISTORY_DIR = Path(__file__).resolve().parent / "history_images"

CLASS_COLORS = [
    (102, 230,  76), (242, 242, 242), (242, 128,  51),
    ( 26, 166, 242), (217,  77, 191), ( 51, 217, 242),
    (200,  90, 240), (180, 220,  80),
]


# ── 헬퍼 ──────────────────────────────────────
def cv2_to_imgtk(bgr: np.ndarray, target_size: Tuple[int, int]):
    h, w = bgr.shape[:2]
    tw, th = target_size
    scale = min(tw / w, th / h)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    resized = cv2.resize(bgr, (nw, nh))
    canvas = np.zeros((th, tw, 3), dtype=np.uint8)
    px, py = (tw - nw) // 2, (th - nh) // 2
    canvas[py:py + nh, px:px + nw] = resized
    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    return ImageTk.PhotoImage(PILImage.fromarray(rgb)), scale, (px, py)


def depth_to_heatmap(depth_mm: np.ndarray,
                     valid_mask: Optional[np.ndarray] = None) -> np.ndarray:
    d = depth_mm.astype(np.float32)
    if valid_mask is None:
        valid_mask = d > 0
    if valid_mask.any():
        vmin = float(d[valid_mask].min())
        vmax = float(d[valid_mask].max())
        norm = np.clip((d - vmin) / (vmax - vmin), 0, 1) if vmax > vmin else np.zeros_like(d)
    else:
        norm = np.zeros_like(d)
    u8 = (norm * 255).astype(np.uint8)
    u8[~valid_mask] = 0
    hm = cv2.applyColorMap(u8, cv2.COLORMAP_JET)
    hm[~valid_mask] = 0
    return hm


def expand_bbox_2x(bbox: Tuple[int, int, int, int],
                   img_w: int, img_h: int,
                   factor: float = 2.0) -> Tuple[int, int, int, int]:
    """bbox 를 중심점 유지하면서 factor 배 확장. 이미지 경계로 클립."""
    x1, y1, x2, y2 = (int(v) for v in bbox)
    cx = (x1 + x2) * 0.5
    cy = (y1 + y2) * 0.5
    w = (x2 - x1) * factor
    h = (y2 - y1) * factor
    nx1 = int(round(max(0, cx - w * 0.5)))
    ny1 = int(round(max(0, cy - h * 0.5)))
    nx2 = int(round(min(img_w, cx + w * 0.5)))
    ny2 = int(round(min(img_h, cy + h * 0.5)))
    if nx2 <= nx1 or ny2 <= ny1:
        return (x1, y1, x2, y2)
    return (nx1, ny1, nx2, ny2)


# ── 메인 GUI ──────────────────────────────────
class GraspGUI(tk.Tk):

    def __init__(self, weights_path: Path, device: str, vlm_model: str,
                 execute_motion: bool = True,
                 gripper_type: str = "rg2",
                 gripper_ip: Optional[str] = "192.168.1.1",
                 gripper_port: int = 502,
                 quality_min: float = 0.5,
                 planarity_min: float = 0.3,
                 non_planarity_max: float = 0.10,
                 approach_offset_mm: float = 50.0):
        super().__init__()
        self.title("Semantic Grasp — Click-to-Test"
                   + (" [EXECUTE MODE]" if execute_motion else " [PERCEPTION ONLY]"))
        self.geometry("1500x980")
        self.configure(bg="#1a1a1f")

        self._log_q: "queue.Queue[str]" = queue.Queue()
        self._result_q: "queue.Queue[tuple]" = queue.Queue()
        self._state_lock = threading.Lock()

        self.live_dets: list[Detection] = []
        self.last_color: Optional[np.ndarray] = None
        self.live_scale = 1.0
        self.live_pad = (0, 0)
        self.busy = False
        self._vlm: Optional[VLMClient] = None
        self._vlm_model = vlm_model

        # 모션 관련
        self.execute_motion = execute_motion
        self.gripper_type = gripper_type
        self.gripper_ip = gripper_ip
        self.gripper_port = gripper_port
        self.quality_min = quality_min
        self.planarity_min = planarity_min
        self.non_planarity_max = non_planarity_max
        self.approach_offset_mm = approach_offset_mm
        self.motion: Optional[DoosanGripperMotion] = None
        self._dsr_setup_done = False

        self._build_widgets()
        self._init_stages()

        self.log("rclpy.init()")
        rclpy.init()
        self.img_node = ImgNode()
        self.executor = SingleThreadedExecutor()
        self.executor.add_node(self.img_node)
        self.ros_thread = threading.Thread(target=self._spin_ros, daemon=True)
        self.ros_thread.start()
        self.log("ROS spin thread started")

        self.log(f"YOLO 로딩: {weights_path}")
        self.yolo = YoloDetector(weights_path, device=device, conf=0.6, iou=0.45)
        self.log(f"YOLO classes: {self.yolo.names}")
        self.log(f"YOLO 초기 conf={self.yolo.conf:.2f} iou={self.yolo.iou:.2f}")

        try:
            self.T_gripper2cam = load_handeye_matrix()
            self.log(f"Hand-eye matrix loaded shape={self.T_gripper2cam.shape}")
        except Exception as e:
            self.log(f"Hand-eye 로드 실패: {e}")
            self.T_gripper2cam = None

        HISTORY_DIR.mkdir(exist_ok=True)
        self.log(f"history dir: {HISTORY_DIR}")

        self._info_set("Status: IDLE\n라이브 뷰의 bbox 를 클릭하세요\n")

        self.after(TICK_MS, self._tick_live)
        self.after(LOG_DRAIN_MS, self._drain_log_queue)
        self.after(RESULT_DRAIN_MS, self._drain_result_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ─── widgets ─────────────────────────────
    def _build_widgets(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        top = ttk.Frame(self, padding=6)
        top.pack(side="top", fill="x")
        self.status_var = tk.StringVar(value="INITIALIZING…")
        ttk.Label(top, textvariable=self.status_var,
                  font=("Sans", 11, "bold")).pack(side="left")
        ttk.Button(top, text="Reset", command=self._reset).pack(side="right", padx=4)
        ttk.Button(top, text="Quit", command=self._on_close).pack(side="right", padx=4)
        # 홈 버튼 — 모션 모드일 때만 활성. movej 로 안전 자세 이동
        self._home_btn = ttk.Button(top, text="🏠 Home",
                                    command=self._on_home_clicked)
        self._home_btn.pack(side="right", padx=4)
        if not self.execute_motion:
            self._home_btn.state(["disabled"])

        # Scan Point 버튼 — joint(0,0,42,0,136.3,0) 으로 이동 (사물 스캔 시점)
        self._scan_btn = ttk.Button(top, text="📍 Scan Point",
                                    command=self._on_scan_point_clicked)
        self._scan_btn.pack(side="right", padx=4)
        if not self.execute_motion:
            self._scan_btn.state(["disabled"])

        main = ttk.Frame(self)
        main.pack(side="top", fill="both", expand=True)
        # 5:5 좌우 분할 — uniform 으로 두 컬럼 동일 너비 강제
        main.columnconfigure(0, weight=1, uniform="cols")
        main.columnconfigure(1, weight=1, uniform="cols")
        main.rowconfigure(0, weight=1)

        # 좌측 컨테이너: 라이브 뷰 + 로그 (세로 구성)
        left_col = ttk.Frame(main)
        left_col.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        left = ttk.LabelFrame(left_col, text="라이브 뷰 (클릭하여 bbox 선택)", padding=4)
        left.pack(side="top", fill="both", expand=True)

        # ── YOLO conf / iou 슬라이더 (라이브 뷰 위) ──
        ctrl_bar = ttk.Frame(left)
        ctrl_bar.pack(side="top", fill="x", pady=(0, 4))

        self.conf_var = tk.DoubleVar(value=0.6)
        self.iou_var = tk.DoubleVar(value=0.45)

        ttk.Label(ctrl_bar, text="conf").pack(side="left", padx=(2, 2))
        self._conf_value_lbl = ttk.Label(ctrl_bar, text=f"{self.conf_var.get():.2f}",
                                         width=4)
        self._conf_value_lbl.pack(side="left")
        conf_scale = ttk.Scale(ctrl_bar, from_=0.05, to=0.95,
                                variable=self.conf_var, orient="horizontal",
                                length=180, command=self._on_conf_changed)
        conf_scale.pack(side="left", padx=(2, 12))

        ttk.Label(ctrl_bar, text="iou").pack(side="left", padx=(2, 2))
        self._iou_value_lbl = ttk.Label(ctrl_bar, text=f"{self.iou_var.get():.2f}",
                                        width=4)
        self._iou_value_lbl.pack(side="left")
        iou_scale = ttk.Scale(ctrl_bar, from_=0.05, to=0.95,
                              variable=self.iou_var, orient="horizontal",
                              length=180, command=self._on_iou_changed)
        iou_scale.pack(side="left", padx=2)

        self.live_canvas = tk.Canvas(left, width=LIVE_W, height=LIVE_H,
                                     bg="black", highlightthickness=0,
                                     cursor="hand2")
        self.live_canvas.pack(fill="both", expand=True)
        self.live_canvas.bind("<Button-1>", self._on_click)

        # 로그 — 라이브 뷰 컨테이너 하단 (left_col 안)
        log_frame = ttk.LabelFrame(left_col, text="로그", padding=4)
        log_frame.pack(side="top", fill="both", expand=False, pady=(4, 0))
        self.log_text = scrolledtext.ScrolledText(
            log_frame, height=16, font=("Mono", 9),
            bg="#0a0a10", fg="#bbf", insertbackground="#fff")
        self.log_text.pack(fill="both", expand=True)

        # 우측: 시각 패널 4 + 진단 체크리스트 (전체가 이미지 출력부)
        right = ttk.Frame(main)
        right.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)

        right.columnconfigure(0, weight=2)         # ① ③
        right.columnconfigure(1, weight=2)         # ② ④
        right.rowconfigure(0, weight=2)            # ① ②  시각 패널
        right.rowconfigure(1, weight=2)            # ③ ④
        right.rowconfigure(2, weight=1)            # ⑤ 진단 체크리스트 (전 컬럼)

        # ① ② ③ ④ 시각 패널 — 2x2 grid
        f1 = ttk.LabelFrame(right, text="① 선택된 객체 crop (YOLO bbox)", padding=4)
        f1.grid(row=0, column=0, padx=2, pady=2, sticky="nsew")
        self.crop_canvas = tk.Canvas(f1, width=THUMB_W, height=THUMB_H,
                                     bg="black", highlightthickness=0)
        self.crop_canvas.pack(fill="both", expand=True)

        f2 = ttk.LabelFrame(right, text="② ROI + approach(노랑) + principal(시안)",
                             padding=4)
        f2.grid(row=0, column=1, padx=2, pady=2, sticky="nsew")
        self.roi_canvas = tk.Canvas(f2, width=THUMB_W, height=THUMB_H,
                                    bg="black", highlightthickness=0)
        self.roi_canvas.pack(fill="both", expand=True)

        f3 = ttk.LabelFrame(right, text="③ depth ROI 필터 후 (jet)", padding=4)
        f3.grid(row=1, column=0, padx=2, pady=2, sticky="nsew")
        self.depth_canvas = tk.Canvas(f3, width=THUMB_W, height=THUMB_H,
                                      bg="black", highlightthickness=0)
        self.depth_canvas.pack(fill="both", expand=True)

        f4 = ttk.LabelFrame(right, text="④ Grasp pose 분석 (스크롤)", padding=4)
        f4.grid(row=1, column=1, padx=2, pady=2, sticky="nsew")
        self.info_text = scrolledtext.ScrolledText(
            f4, width=46, height=18, font=("Mono", 9),
            bg="#101015", fg="#e0e0f0", insertbackground="#fff",
            state="disabled", relief="flat")
        self.info_text.pack(fill="both", expand=True)

        # ⑤ 진단 체크리스트 — 우측 grid 의 마지막 행, 두 컬럼 차지
        f5 = ttk.LabelFrame(right, text="⑤ 진단 체크리스트 (단계별 상태)",
                             padding=4)
        f5.grid(row=2, column=0, columnspan=2, padx=2, pady=2, sticky="nsew")
        self.stage_text = scrolledtext.ScrolledText(
            f5, height=8, font=("Mono", 10),
            bg="#0a1015", fg="#d0e0e0", insertbackground="#fff",
            state="disabled", relief="flat")
        self.stage_text.pack(fill="both", expand=True)

    # ─── ROS ─────────────────────────────────
    def _spin_ros(self):
        try:
            self.executor.spin()
        except Exception as e:
            self.log(f"ROS spin error: {e}")

    def _on_close(self):
        self.log("종료 중...")
        try: self.executor.shutdown()
        except Exception: pass
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception: pass
        try: self.destroy()
        except Exception: pass

    # ─── 로그 ────────────────────────────────
    def log(self, msg: str):
        self._log_q.put(msg)

    def _drain_log_queue(self):
        try:
            while True:
                msg = self._log_q.get_nowait()
                ts = datetime.now().strftime("%H:%M:%S")
                self.log_text.insert("end", f"[{ts}] {msg}\n")
                self.log_text.see("end")
        except queue.Empty:
            pass
        self.after(LOG_DRAIN_MS, self._drain_log_queue)

    # ─── conf / iou 슬라이더 ─────────────────
    def _on_conf_changed(self, val):
        try:
            v = float(val)
        except ValueError:
            return
        self._conf_value_lbl.config(text=f"{v:.2f}")
        if hasattr(self, "yolo") and self.yolo is not None:
            self.yolo.conf = v

    def _on_iou_changed(self, val):
        try:
            v = float(val)
        except ValueError:
            return
        self._iou_value_lbl.config(text=f"{v:.2f}")
        if hasattr(self, "yolo") and self.yolo is not None:
            self.yolo.iou = v

    # ─── 라이브 ──────────────────────────────
    def _tick_live(self):
        try:
            color = self.img_node.get_color_frame()
            if color is None:
                self.status_var.set("RealSense 프레임 대기 중...")
            else:
                try:
                    dets = self.yolo.detect_all(color)
                except Exception as e:
                    self.log(f"YOLO error: {e}")
                    dets = []

                annotated = self._draw_live_overlay(color.copy(), dets)
                # 캔버스 실제 크기 사용 (창 리사이즈 대응)
                cw = max(self.live_canvas.winfo_width(), LIVE_W // 4)
                ch = max(self.live_canvas.winfo_height(), LIVE_H // 4)
                imgtk, scale, pad = cv2_to_imgtk(annotated, (cw, ch))
                with self._state_lock:
                    self.live_dets = dets
                    self.last_color = color
                    self.live_scale = scale
                    self.live_pad = pad
                self._live_imgtk = imgtk
                self.live_canvas.delete("live")
                self.live_canvas.create_image(0, 0, anchor="nw",
                                              image=imgtk, tags="live")
                if not self.busy:
                    self.status_var.set(f"IDLE — bbox {len(dets)}개. 클릭으로 선택")
        finally:
            self.after(TICK_MS, self._tick_live)

    def _draw_live_overlay(self, frame, dets):
        for d in dets:
            color = CLASS_COLORS[d.class_id % len(CLASS_COLORS)]
            x1, y1, x2, y2 = d.box_xyxy
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            label = f"{d.class_name} {d.score:.2f}"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
            cv2.rectangle(frame, (x1, max(0, y1 - th - 6)),
                          (x1 + tw + 6, y1), color, -1)
            cv2.putText(frame, label, (x1 + 3, y1 - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,0,0), 1, cv2.LINE_AA)
        cv2.putText(frame, "click a bbox to analyze",
                    (10, frame.shape[0] - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 1, cv2.LINE_AA)
        return frame

    # ─── 클릭 ────────────────────────────────
    def _on_click(self, event):
        if self.busy:
            self.log("처리 중 — 클릭 무시")
            return
        with self._state_lock:
            dets = list(self.live_dets)
            color = self.last_color.copy() if self.last_color is not None else None
            scale = self.live_scale
            pad_x, pad_y = self.live_pad
        if color is None:
            self.log("프레임 없음")
            return
        depth = self.img_node.get_depth_frame()
        intr = self.img_node.get_camera_intrinsic()
        if depth is None or intr is None:
            self.log("depth/intrinsics 미수신 — RealSense aligned_depth 토픽 확인")
            return
        depth = depth.copy()

        x_img = (event.x - pad_x) / max(1e-6, scale)
        y_img = (event.y - pad_y) / max(1e-6, scale)
        H, W = color.shape[:2]
        if not (0 <= x_img < W and 0 <= y_img < H):
            self.log(f"클릭 ({event.x},{event.y}) 이미지 외부")
            return

        clicked = None
        for d in dets:
            x1, y1, x2, y2 = d.box_xyxy
            if x1 <= x_img <= x2 and y1 <= y_img <= y2:
                if clicked is None:
                    clicked = d
                else:
                    a_new = (x2-x1) * (y2-y1)
                    cx1, cy1, cx2, cy2 = clicked.box_xyxy
                    a_old = (cx2-cx1) * (cy2-cy1)
                    if a_new < a_old:
                        clicked = d
        if clicked is None:
            self.log(f"클릭 ({x_img:.0f},{y_img:.0f}) — bbox 없음")
            return

        self.log(f"선택: {clicked.class_name} conf={clicked.score:.2f} "
                 f"bbox={clicked.box_xyxy}")
        self._start_pipeline(clicked, color, depth, intr)

    # ─── 파이프라인 ─────────────────────────
    def _start_pipeline(self, det: Detection, color, depth, intr):
        self.busy = True
        self._init_stages()
        self._set_stage(0, "✓",
                        f"{det.class_name} (conf {det.score:.2f})")

        crop = crop_bbox(color, det.box_xyxy, pad=8)
        self._show_canvas(self.crop_canvas, crop)
        self._show_canvas(self.roi_canvas, np.zeros_like(crop))
        self._show_canvas(self.depth_canvas, np.zeros_like(crop))
        self._info_set(self._fmt_info_pending(det))

        # 세션 폴더 (각 클릭마다 별도)
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{det.class_name}"
        session_dir = HISTORY_DIR / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        self.log(f"history session: {session_dir.name}")

        # 01_live (현재 클릭한 시점의 라이브 프레임)
        live_at_click = self._draw_live_overlay(color.copy(), [det])
        cv2.imwrite(str(session_dir / "01_live.jpg"), live_at_click)
        # 02_crop (YOLO bbox crop)
        cv2.imwrite(str(session_dir / "02_crop.jpg"), crop)

        # ── 클래스 분기: plate 만 VLM, 그 외는 YOLO bbox 직접 사용 ──
        label = det.class_name.strip().lower()
        snap = (det, color, depth, intr, crop, session_dir)

        if label == "plate":
            self._set_stage(1, "🌀", "VLM (plate) 호출 중...")
            self.status_var.set(f"VLM 호출 중: {det.class_name}…")
            prompt = make_grasp_prompt(det.class_name, crop.shape[1], crop.shape[0])
            self.log(f"VLM 프롬프트 ↓\n{prompt}")
            (session_dir / "00_prompt.txt").write_text(prompt)
            threading.Thread(target=self._vlm_worker, args=(snap,), daemon=True).start()
        else:
            self._set_stage(1, "⏭",
                            f"{det.class_name} → YOLO bbox 직접 사용 (VLM 생략)")
            self.status_var.set(f"분석 중 (no VLM): {det.class_name}…")
            self.log(f"[{det.class_name}] VLM 호출 생략 — YOLO bbox 그대로 ROI")
            crop_h, crop_w = crop.shape[:2]
            # crop 좌표계에서 (8, 8, w-8, h-8) = pad 제외 영역 = YOLO bbox 영역
            x1, y1, x2, y2 = det.box_xyxy
            bw, bh = x2 - x1, y2 - y1
            fake_roi = GraspROI(
                bbox=(8, 8, 8 + bw, 8 + bh),
                reason=f"non-plate ({det.class_name}): YOLO bbox 직접 사용",
                raw_response="", prompt="")
            # 직접 _on_vlm_ok 호출 (VLM 워커 우회)
            self._on_vlm_ok(snap, fake_roi)

    def _vlm_worker(self, snap):
        det, color, depth, intr, crop, session_dir = snap
        try:
            if self._vlm is None:
                self.log(f"VLMClient 초기화 (model={self._vlm_model})")
                self._vlm = VLMClient(model=self._vlm_model)
            self.log(f"VLM 요청: crop {crop.shape[1]}x{crop.shape[0]} "
                     f"label='{det.class_name}'")
            roi = self._vlm.query_grasp_roi(crop, det.class_name)
            self._result_q.put(("vlm_ok", snap, roi))
        except Exception as e:
            tb = traceback.format_exc()
            self._result_q.put(("vlm_err", snap, (str(e), tb)))

    def _drain_result_queue(self):
        try:
            while True:
                kind, snap, payload = self._result_q.get_nowait()
                if kind == "vlm_ok":
                    self._on_vlm_ok(snap, payload)
                elif kind == "vlm_err":
                    self._on_vlm_err(snap, payload)
                elif kind == "motion_done":
                    self._on_motion_done(snap, payload)
                elif kind == "motion_err":
                    self._on_motion_err(snap, payload)
                else:
                    self.log(f"unknown result kind: {kind!r}")
        except queue.Empty:
            pass
        except Exception as e:
            self.log(f"_drain_result error: {e}\n{traceback.format_exc()}")
            self.busy = False
        self.after(RESULT_DRAIN_MS, self._drain_result_queue)

    def _on_vlm_err(self, snap, payload):
        det, color, depth, intr, crop, session_dir = snap
        msg, tb = payload
        self.log(f"VLM 실패: {msg}")
        for ln in tb.splitlines()[-6:]:
            self.log(f"  {ln}")
        (session_dir / "ERROR.txt").write_text(f"{msg}\n\n{tb}")
        self._set_stage(1, "✗", f"VLM 실패: {msg[:50]}")
        self.status_var.set("VLM 실패 — 로그 참조 후 Reset")
        self.busy = False

    def _on_vlm_ok(self, snap, roi: GraspROI):
        det, color, depth, intr, crop, session_dir = snap

        cx1 = max(0, int(det.box_xyxy[0]) - 8)
        cy1 = max(0, int(det.box_xyxy[1]) - 8)
        global_roi_raw = to_global_bbox(roi.bbox, (cx1, cy1))

        # plate 만 ROI 를 2x 확장. 비-plate 는 YOLO bbox 그대로 사용 (워크벤치 confusion 방지)
        H, W = color.shape[:2]
        label = det.class_name.strip().lower()
        if label == "plate":
            global_roi = expand_bbox_2x(global_roi_raw, W, H)
            self._set_stage(1, "✓",
                            f"VLM ROI={roi.bbox} → 2x 확장")
            self.log(
                f"[plate] VLM ROI crop={roi.bbox}  global(raw)={global_roi_raw}  "
                f"global(×2)={global_roi}  reason={roi.reason!r}")
        else:
            global_roi = global_roi_raw
            self.log(
                f"[{det.class_name}] ROI = YOLO bbox 그대로 = {global_roi_raw}")
        (session_dir / "03_vlm_response.json").write_text(
            json.dumps({"bbox_crop": list(roi.bbox),
                        "bbox_global_raw": list(global_roi_raw),
                        "bbox_global": list(global_roi),  # 확장 후 (downstream 사용)
                        "expand_factor": 2.0,
                        "reason": roi.reason,
                        "raw": roi.raw_response},
                       ensure_ascii=False, indent=2))

        # ── ROI overlay (간이) ──
        crop_anno = crop.copy()
        rx1, ry1, rx2, ry2 = roi.bbox
        cv2.rectangle(crop_anno, (rx1, ry1), (rx2, ry2), (0, 0, 255), 2)
        cv2.putText(crop_anno, "VLM ROI", (rx1, max(0, ry1 - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
        cv2.imwrite(str(session_dir / "03_vlm_roi.jpg"), crop_anno)

        # ── 1) 법선 추정용 점운 ──
        # 두 가지 후보:
        #   (a) BBox 전체 점운 — 단일 표면 객체(폰/접시/책)에 적합
        #   (b) ROI 를 1.6배 확장한 영역 — 손잡이 객체에서 본체 표면 섞임 방지
        # 둘 다 산출 후 planarity 가 더 높은 쪽을 채택 (자동 선택).
        self.status_var.set("BBox/ROI 확장 점운 추출 중...")
        bbox_mask = filter_depth_roi(depth, det.box_xyxy, median_band_mm=80.0)
        bbox_pts = (deproject_mask(depth, bbox_mask, intr, max_points=4000)
                    if bbox_mask is not None else None)
        if bbox_pts is not None:
            self.log(f"  cand-A BBox 점운: N={bbox_pts.shape[0]}px")

        # ROI 확장 (1.6배)
        rgx1, rgy1, rgx2, rgy2 = global_roi
        rw, rh = rgx2 - rgx1, rgy2 - rgy1
        ex_x = int(rw * 0.3)
        ex_y = int(rh * 0.3)
        roi_expanded = (rgx1 - ex_x, rgy1 - ex_y, rgx2 + ex_x, rgy2 + ex_y)
        ex_mask = filter_depth_roi(depth, roi_expanded, median_band_mm=50.0)
        ex_pts = (deproject_mask(depth, ex_mask, intr, max_points=4000)
                  if ex_mask is not None else None)
        if ex_pts is not None:
            self.log(f"  cand-B 확장 ROI 점운: N={ex_pts.shape[0]}px")

        # ── 2) ROI 점운 (위치 산출용) ──
        self.status_var.set("Depth 필터 + PCA 분석 중...")
        mask = filter_depth_roi(depth, global_roi, median_band_mm=50.0)
        if mask is None:
            self.log("ROI depth 필터 실패")
            self._set_stage(2, "✗", "유효 픽셀 부족")
            self.status_var.set("Depth 필터 실패")
            self.busy = False
            return
        n_valid = int(mask.sum())
        gx1, gy1, gx2, gy2 = global_roi
        depth_roi = depth[gy1:gy2, gx1:gx2].copy()
        mask_roi = mask[gy1:gy2, gx1:gx2]
        roi_area = max(1, (gx2-gx1) * (gy2-gy1))
        pass_rate = 100.0 * n_valid / roi_area
        depth_median_mm = float(np.median(depth_roi[depth_roi > 0])) if (depth_roi > 0).any() else 0.0
        self.log(f"ROI {gx2-gx1}x{gy2-gy1}  유효 {n_valid}px ({pass_rate:.0f}%) "
                 f"median={depth_median_mm:.0f}mm")
        # stage 3: 필터 통과율 < 10% 면 경고 (블록이 검정 hole 되는 케이스 감지)
        if pass_rate < 10.0:
            self._set_stage(2, "⚠",
                            f"통과율 {pass_rate:.0f}% — 사물이 필터에서 제거된 듯")
        else:
            self._set_stage(2, "✓",
                            f"{n_valid}px / {roi_area}px ({pass_rate:.0f}%) "
                            f"median={depth_median_mm:.0f}mm")

        # ③ heatmap
        heatmap = depth_to_heatmap(depth_roi, mask_roi)
        cnts, _ = cv2.findContours(mask_roi.astype(np.uint8) * 255,
                                    cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(heatmap, cnts, -1, (255, 255, 255), 1)
        self._show_canvas(self.depth_canvas, heatmap)
        cv2.imwrite(str(session_dir / "04_depth_heatmap.jpg"), heatmap)

        pts = deproject_mask(depth, mask, intr, max_points=4000)
        self.log(f"ROI 점운 (centroid 용): N={pts.shape[0]}px")

        # ── 클래스 기반 PCA 분기 (compute_grasp_pose 가 target_class 로 mode 선택) ──
        # plate=radial, banana=cylindrical, 그 외=spherical
        candidates = []
        if bbox_pts is not None and bbox_pts.shape[0] >= 50:
            p_a = compute_grasp_pose(pts, normal_points=bbox_pts,
                                     target_class=det.class_name)
            if p_a is not None:
                candidates.append(("BBox", p_a, bbox_pts.shape[0]))
        if ex_pts is not None and ex_pts.shape[0] >= 50:
            p_b = compute_grasp_pose(pts, normal_points=ex_pts,
                                     target_class=det.class_name)
            if p_b is not None:
                candidates.append(("ROI×1.6", p_b, ex_pts.shape[0]))
        # 마지막 안전망: ROI 점운만으로
        p_c = compute_grasp_pose(pts, target_class=det.class_name)
        if p_c is not None:
            candidates.append(("ROI only", p_c, pts.shape[0]))

        if not candidates:
            self.log("grasp pose 계산 실패 (모든 후보 퇴화)")
            self._set_stage(3, "✗", "모든 후보 퇴화")
            self.status_var.set("PCA 실패")
            self.busy = False
            return

        # planarity 최대 채택
        for name, p, n in candidates:
            self.log(f"  cand[{name}] N={n} mode={p.grasp_mode} "
                     f"planarity={p.planarity:.2f} linearity={p.linearity:.2f} "
                     f"q={p.quality:.2f}")
        best = max(candidates, key=lambda c: c[1].planarity)
        normal_source, pose, _ = best
        self.log(f"  → 채택: '{normal_source}' mode={pose.grasp_mode} "
                 f"q={pose.quality:.2f}")
        self._set_stage(3, "✓",
                        f"mode={pose.grasp_mode}  source={normal_source}  "
                        f"q={pose.quality:.2f}")

        # ── 상세 PCA 로그 ──
        e0, e1, e2 = pose.eigvals
        self.log(f"PCA eigvals: λ1={e0:.5f} λ2={e1:.5f} λ3={e2:.5f}")
        self.log(f"  linearity={pose.linearity:.2f}  "
                 f"planarity={pose.planarity:.2f}  q={pose.quality:.2f}")
        self.log(f"  tilt={pose.tilt_deg:.1f} deg  azimuth={pose.azimuth_deg:+.1f} deg  "
                 f"principal_yaw={pose.principal_yaw_deg:+.1f} deg")
        self.log(f"  approach(cam)={np.round(pose.rotation[:,2],2).tolist()}")
        self.log(f"  principal(cam)={np.round(pose.axes[:,0],2).tolist()}")
        if pose.planarity > 0.6:
            self.log("  ✓ 평면 적합 양호 — 법선 신뢰도 OK")
        elif pose.linearity > 0.9:
            self.log("  ⚠ 점운이 1D 에 가까움 — 법선 신뢰도 낮음 (BBox 가 얇거나 노이즈 큼)")
        else:
            self.log("  ~ 평면 적합 보통")

        # ── ② annotated full-frame (approach + principal + tilt label) ──
        annotated = color.copy()
        self._draw_dets_on(annotated, [det])
        cv2.rectangle(annotated, (gx1, gy1), (gx2, gy2), (0, 0, 255), 2)
        self._draw_approach_arrow(annotated, pose, intr)
        self._draw_principal_axis(annotated, pose, intr)
        self._draw_angle_label(annotated, pose, intr)
        # ② 패널은 객체 주변만 잘라서 표시
        x1, y1, x2, y2 = det.box_xyxy
        pad = 30
        H, W = annotated.shape[:2]
        view = annotated[max(0, y1-pad):min(H, y2+pad),
                         max(0, x1-pad):min(W, x2+pad)]
        if view.size == 0:
            view = annotated
        self._show_canvas(self.roi_canvas, view)
        cv2.imwrite(str(session_dir / "05_annotated_full.jpg"), annotated)
        cv2.imwrite(str(session_dir / "05_annotated_view.jpg"), view)

        # base 변환 (가상 home pose 기준)
        base_pose = None
        if self.T_gripper2cam is not None:
            try:
                base2g = get_robot_pose_matrix(400.0, 0.0, 400.0, 0.0, 90.0, 0.0)
                base_pose = cam_pose_to_base_pose(
                    pose.position, pose.rotation, self.T_gripper2cam, base2g)
            except Exception as e:
                self.log(f"base 변환 실패: {e}")

        # ── 워크벤치 plane 추정 → 동적 approach_offset ──
        APPROACH_OFFSET_CAP_MM = 80.0
        wb = estimate_workbench_plane(depth, det.box_xyxy, intr, pad_px=80)
        wb_info = None
        if wb is not None:
            wb_centroid_m, wb_normal = wb
            obj_height_m = perpendicular_distance(
                pose.position, wb_centroid_m, wb_normal)
            obj_height_mm = obj_height_m * 1000.0
            # h/2 + 20mm 추가 진입 (사용자 보정), cap 으로 클램프
            dyn_offset_mm = max(0.0, min(obj_height_mm / 2.0 + 20.0, APPROACH_OFFSET_CAP_MM))
            wb_info = {
                "centroid_m": wb_centroid_m.tolist(),
                "normal": wb_normal.tolist(),
                "obj_height_mm": obj_height_mm,
                "dyn_offset_mm": dyn_offset_mm,
                "cap_mm": APPROACH_OFFSET_CAP_MM,
            }
            self.log(f"workbench plane OK — obj_height={obj_height_mm:.1f}mm "
                     f"→ dyn approach_offset={dyn_offset_mm:.1f}mm "
                     f"(cap={APPROACH_OFFSET_CAP_MM:.0f})")
            self._set_stage(4, "✓",
                            f"obj_height={obj_height_mm:.1f}mm")
            self._set_stage(5, "✓",
                            f"approach_offset={dyn_offset_mm:.1f}mm "
                            f"(cap={APPROACH_OFFSET_CAP_MM:.0f}mm)")
        else:
            self.log("workbench plane 추정 실패 — 기본 approach_offset 사용")
            self._set_stage(4, "⚠", "워크벤치 plane 추정 실패")
            self._set_stage(5, "⚠", "기본 offset 사용 (50mm)")

        info = self._fmt_info_done(det, global_roi, roi, pose, n_valid, base_pose,
                                   wb_info=wb_info, n_pixels_total=roi_area,
                                   pass_rate=pass_rate)
        self._info_set(info)
        (session_dir / "06_pose_info.txt").write_text(info)

        # JSON 형태로도 저장 (재현/그래프용)
        pose_json = {
            "class": det.class_name, "score": det.score,
            "bbox": list(det.box_xyxy), "vlm_roi_global": list(global_roi),
            "vlm_reason": roi.reason,
            "normal_source": normal_source,
            "n_points_centroid": pose.n_points_centroid,
            "n_points_normal": pose.n_points_normal,
            "eigvals": pose.eigvals.tolist(),
            "linearity": pose.linearity, "planarity": pose.planarity,
            "quality": pose.quality,
            "width_mm": pose.width * 1000.0,
            "tilt_deg": pose.tilt_deg, "azimuth_deg": pose.azimuth_deg,
            "principal_yaw_deg": pose.principal_yaw_deg,
            "position_m_cam": pose.position.tolist(),
            "rotation_cam": pose.rotation.tolist(),
            "approach_unit_cam": pose.rotation[:,2].tolist(),
            "principal_axis_cam": pose.axes[:,0].tolist(),
            "base_pose_mm_deg": list(base_pose) if base_pose else None,
        }
        (session_dir / "07_pose.json").write_text(
            json.dumps(pose_json, ensure_ascii=False, indent=2))

        self.log(f"history saved → {session_dir}")
        self.status_var.set(
            f"DONE — {det.class_name}  "
            f"width={pose.width*1000:.1f}mm  tilt={pose.tilt_deg:.0f} deg  "
            f"q={pose.quality:.2f}")

        # ── quality 게이트 (motion 실행 안 해도 진단 가치) ──
        gate_pass = True
        gate_msgs = []
        if pose.quality < self.quality_min:
            gate_pass = False
            gate_msgs.append(f"quality {pose.quality:.2f}<{self.quality_min:.2f}")
        if pose.planarity < self.planarity_min and pose.grasp_mode == "radial":
            # radial mode (plate) 만 planarity 검사
            gate_pass = False
            gate_msgs.append(f"planarity {pose.planarity:.2f}<{self.planarity_min:.2f}")
        l1 = float(max(1e-12, pose.eigvals[0]))
        l3 = float(max(0.0, pose.eigvals[2]))
        non_planarity = (l3 / l1) ** 0.5
        if non_planarity > self.non_planarity_max and pose.grasp_mode == "radial":
            gate_pass = False
            gate_msgs.append(f"non-planar {non_planarity:.0%}>{self.non_planarity_max:.0%}")
        if gate_pass:
            self._set_stage(6, "✓", f"q={pose.quality:.2f} ≥ {self.quality_min:.2f}")
        else:
            self._set_stage(6, "✗", " / ".join(gate_msgs))

        # ── 모션 실행 (--execute 모드일 때만) ──
        if self.execute_motion:
            if not gate_pass:
                for m in gate_msgs:
                    self.log(f"⚠ 게이트 차단: {m} — 모션 스킵")
                self._set_stage(7, "⏭", "게이트 미통과로 motion 생략")
                self.busy = False
                return
            # 사용자 확인 (modal)
            confirm = messagebox.askyesno(
                "Robot Motion 확인",
                f"실 로봇이 '{det.class_name}' 으로 이동·파지합니다.\n\n"
                f"  width    = {pose.width*1000:.1f} mm\n"
                f"  tilt     = {pose.tilt_deg:.1f}°\n"
                f"  quality  = {pose.quality:.2f}\n"
                f"  planarity= {pose.planarity:.2f}\n\n"
                f"진행하시겠습니까?\n"
                f"(E-stop, 안전 거리, RG2 활성 확인 후 Yes)",
                parent=self,
            )
            if not confirm:
                self.log("사용자 취소 — 모션 스킵")
                self._set_stage(7, "⏭", "사용자 취소")
                self.busy = False
                return
            self.status_var.set(f"모션 실행 중: {det.class_name}…")
            self.log(f"=== motion start: {det.class_name} ===")
            self._set_stage(7, "🌀", "DSR motion 실행 중")
            threading.Thread(target=self._motion_worker,
                             args=(pose, det.class_name, session_dir),
                             daemon=True).start()
            return  # busy 는 motion_done/err 에서 해제
        else:
            # 분석 전용 모드 (--execute 안 줌) — motion 단계는 "분석만" 으로 표기
            self._set_stage(7, "—", "분석 모드 (모션 미실행)")

        self.busy = False

    # ─── 시각화 헬퍼 ────────────────────────
    def _draw_dets_on(self, frame, dets):
        for d in dets:
            color = CLASS_COLORS[d.class_id % len(CLASS_COLORS)]
            x1, y1, x2, y2 = d.box_xyxy
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

    def _draw_approach_arrow(self, frame, pose: GraspPose, intr: dict):
        """approach 방향: pre-grasp(10cm) → centroid 노란 화살표."""
        approach = pose.rotation[:, 2]
        pos = pose.position
        pre = pos - approach * 0.10
        a, b = project_to_image(pre, intr), project_to_image(pos, intr)
        if not (a and b):
            return
        H, W = frame.shape[:2]
        if not (0 <= b[0] < W and 0 <= b[1] < H):
            return
        cv2.arrowedLine(frame, a, b, (0, 255, 255), 3, tipLength=0.25)
        cv2.circle(frame, b, 5, (0, 255, 255), -1)

    def _draw_principal_axis(self, frame, pose: GraspPose, intr: dict):
        """principal axis: centroid 양쪽 ±5cm 시안 선."""
        pos = pose.position
        principal = pose.axes[:, 0]
        a = project_to_image(pos + principal * 0.05, intr)
        b = project_to_image(pos - principal * 0.05, intr)
        if a and b:
            cv2.line(frame, a, b, (255, 255, 0), 2)
            cv2.putText(frame, "principal", (a[0]+5, a[1]-5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                        (255, 255, 0), 1, cv2.LINE_AA)

    def _draw_angle_label(self, frame, pose: GraspPose, intr: dict):
        """centroid 옆에 tilt 각도 + width 텍스트."""
        p = project_to_image(pose.position, intr)
        if p is None:
            return
        text = f"tilt={pose.tilt_deg:.0f} deg  w={pose.width*1000:.0f}mm"
        org = (p[0] + 14, p[1] - 14)
        cv2.putText(frame, text, org, cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(frame, text, org, cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    (0, 255, 255), 2, cv2.LINE_AA)

    def _show_canvas(self, canvas: tk.Canvas, bgr: np.ndarray):
        imgtk, _, _ = cv2_to_imgtk(bgr, (THUMB_W, THUMB_H))
        canvas._imgtk = imgtk
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=imgtk)

    # ─── 진단 체크리스트 (단계별 상태) ────────
    STAGE_NAMES = [
        "1. YOLO 탐지",
        "2. ROI 결정 (plate=VLM, 그 외=bbox)",
        "3. depth ROI 필터",
        "4. PCA grasp pose (mode 분기)",
        "5. workbench plane 추정",
        "6. 동적 approach_offset",
        "7. quality 게이트",
        "8. motion 준비",
    ]

    def _init_stages(self):
        # status 마커: ⏳ 대기, 🌀 진행중, ✓ 통과, ✗ 실패, ⚠ 경고, ⏭ 생략
        self.stages = [(name, "⏳", "—") for name in self.STAGE_NAMES]
        self._render_stages()

    def _set_stage(self, idx: int, status: str, detail: str):
        if 0 <= idx < len(self.stages):
            name, _, _ = self.stages[idx]
            self.stages[idx] = (name, status, detail)
            self._render_stages()

    def _render_stages(self):
        if not hasattr(self, "stages") or not self.stages:
            return
        lines = [
            f"{status}  {name:<38s} {detail}"
            for name, status, detail in self.stages
        ]
        self.stage_text.configure(state="normal")
        self.stage_text.delete("1.0", "end")
        self.stage_text.insert("end", "\n".join(lines))
        self.stage_text.configure(state="disabled")

    # ─── 정보 텍스트 ────────────────────────
    def _info_set(self, text: str):
        self.info_text.configure(state="normal")
        self.info_text.delete("1.0", "end")
        self.info_text.insert("end", text)
        self.info_text.configure(state="disabled")

    def _fmt_info_pending(self, det: Detection) -> str:
        x1, y1, x2, y2 = det.box_xyxy
        return (
            f"Status:  VLM PENDING\n"
            f"Class:   {det.class_name}  (conf {det.score:.2f})\n"
            f"BBox:    [{x1}, {y1}, {x2}, {y2}]\n"
            f"Size:    {x2-x1}x{y2-y1}\n\n"
            f"...VLM 응답 대기 중...\n"
        )

    def _fmt_info_done(self, det, global_roi, roi, pose, n_valid, base_pose,
                       wb_info=None, n_pixels_total=None, pass_rate=None):
        approach = pose.rotation[:, 2]
        principal = pose.axes[:, 0]
        x1, y1, x2, y2 = det.box_xyxy
        gx1, gy1, gx2, gy2 = global_roi
        plan_tag = ("양호" if pose.planarity > 0.6
                    else "보통" if pose.planarity > 0.3 else "부족")
        mode_tag = {
            "radial":      "방사형 (plate)",
            "cylindrical": "원통/길쭉 (banana)",
            "spherical":   "구체 (그 외)",
        }.get(pose.grasp_mode, pose.grasp_mode or "unknown")
        L = [
            f"Status:     ANALYSIS DONE",
            f"Class:      {det.class_name}  (conf {det.score:.2f})",
            f"Mode:       ★ {pose.grasp_mode}  — {mode_tag}",
            f"BBox:       [{x1}, {y1}, {x2}, {y2}]",
            f"ROI:        [{gx1}, {gy1}, {gx2}, {gy2}]",
            f"Reason:     {roi.reason}",
            f"",
            f"── depth 필터 ──",
        ]
        if pass_rate is not None and n_pixels_total is not None:
            L += [
                f"통과 픽셀:  {n_valid} / {n_pixels_total} ({pass_rate:.0f}%)",
            ]
        L += [
            f"",
            f"── PCA 진단 ──",
            f"PointCloud: roi={pose.n_points_centroid}  normal={pose.n_points_normal}",
            f"eigvals:    [{pose.eigvals[0]:.4f}, {pose.eigvals[1]:.4f}, "
            f"{pose.eigvals[2]:.4f}]",
            f"linearity:  {pose.linearity:.2f}",
            f"planarity:  {pose.planarity:.2f}   ← {plan_tag}",
            f"quality:    {pose.quality:.2f}",
            f"",
            f"── 워크벤치 plane ──",
        ]
        if wb_info is not None:
            L += [
                f"normal(cam): [{wb_info['normal'][0]:+.2f}, "
                f"{wb_info['normal'][1]:+.2f}, {wb_info['normal'][2]:+.2f}]",
                f"obj_height: {wb_info['obj_height_mm']:6.1f} mm",
                f"dyn_offset: {wb_info['dyn_offset_mm']:6.1f} mm  "
                f"(cap={wb_info['cap_mm']:.0f} mm)",
            ]
        else:
            L += [f"(추정 실패 — 기본 offset 사용)"]
        L += [
            f"",
            f"── 그리퍼 접근 자세 ──",
            f"Width:      {pose.width*1000:.1f} mm",
            f"Position(m, cam):",
            f"  X={pose.position[0]:+.3f}  Y={pose.position[1]:+.3f}  "
            f"Z={pose.position[2]:+.3f}",
            f"",
            f"Tilt:       {pose.tilt_deg:5.1f} deg  (cam +Z 와 approach 의 각)",
            f"Azimuth:    {pose.azimuth_deg:+5.1f} deg  (이미지 평면 approach 방향)",
            f"P-Yaw:      {pose.principal_yaw_deg:+5.1f} deg  (principal vs +X)",
            f"",
            f"Approach:   [{approach[0]:+.2f}, {approach[1]:+.2f}, "
            f"{approach[2]:+.2f}]",
            f"Principal:  [{principal[0]:+.2f}, {principal[1]:+.2f}, "
            f"{principal[2]:+.2f}]",
        ]
        if base_pose is not None:
            L += [
                "",
                "Base pose [mm, deg] (가상 home={400,0,400,0,90,0}):",
                f"  X={base_pose[0]:+.1f}  Y={base_pose[1]:+.1f}  "
                f"Z={base_pose[2]:+.1f}",
                f"  Rx={base_pose[3]:+.2f}  Ry={base_pose[4]:+.2f}  "
                f"Rz={base_pose[5]:+.2f}",
                "",
                "(실로봇 시 현재 posx 기준 재계산)",
            ]
        return "\n".join(L)

    # ─── 모션 실행 ─────────────────────────
    def _motion_worker(self, pose: GraspPose, label: str,
                       session_dir: Optional[Path] = None):
        """별도 스레드에서 DSR/RG 호출. 결과는 큐로 메인 스레드에 전달.

        주의: img_node 는 self.executor 에서 spin 중이므로 DSR 의
        spin_until_future_complete 가 같은 노드로 호출되면 데드락.
        → DSR 전용 노드를 별도 생성 (어떤 executor 에도 추가하지 않음).

        session_dir: history_images 의 현재 세션 폴더. on_pre_close 콜백에서
                    08_at_target_before_close.jpg 저장에 사용.
        """
        try:
            if not self._dsr_setup_done:
                self._log_q.put("[motion] DSR client node 생성 중...")
                from rclpy.node import Node as _RclNode
                # DSR_ROBOT2.py 가 상대경로 서비스명 (aux_control/...) 을 사용하므로
                # 반드시 /dsr01 namespace 에서 생성해야 /dsr01/aux_control/... 로 해석됨.
                self._dsr_node = _RclNode("grasp_gui_dsr_client",
                                          namespace="dsr01")
                self._log_q.put(
                    f"[motion] DSR node='{self._dsr_node.get_name()}' "
                    f"namespace='{self._dsr_node.get_namespace()}' "
                    f"setup_dsr() 호출")
                setup_dsr(self._dsr_node)
                self._dsr_setup_done = True
                self._log_q.put("[motion] DSR setup 완료")
            if self.motion is None:
                self._log_q.put(
                    f"[motion] DoosanGripperMotion 초기화 "
                    f"(type={self.gripper_type} ip={self.gripper_ip})")
                self.motion = DoosanGripperMotion(
                    dryrun=False,
                    gripper_type=self.gripper_type,
                    gripper_ip=self.gripper_ip,
                    gripper_port=self.gripper_port,
                    approach_offset_mm=self.approach_offset_mm,
                    logger=lambda m: self._log_q.put(m))
                self._log_q.put(
                    f"[motion] DoosanGripperMotion 준비 완료 "
                    f"(approach_offset={self.approach_offset_mm:+.1f}mm)")
            self._log_q.put(f"[motion] execute_two_phase() 시작 — {label}")

            # target 도달 후 close 직전: 카메라 시야 1장 캡처 (시각적 피드백)
            def _on_pre_close():
                if session_dir is None:
                    return
                color = self.img_node.get_color_frame()
                if color is None:
                    self._log_q.put("[capture] color frame 없음 — 캡처 스킵")
                    return
                fn = "08_at_target_before_close.jpg"
                cv2.imwrite(str(session_dir / fn), color.copy())
                h, w = color.shape[:2]
                self._log_q.put(f"[capture] {fn}  ({w}x{h})  → {session_dir.name}/")

            # Phase 2 재탐지 콜백 — Phase 1 도달 후 호출됨
            def _redetect():
                return self._redetect_pose_for_phase2(label, session_dir)

            result = self.motion.execute_two_phase(
                pose, redetect_callback=_redetect,
                intermediate_z_mm=450.0,
                on_pre_close=_on_pre_close)
            self._log_q.put(
                f"[motion] execute_two_phase() 종료 — success={result.success}")
            self._result_q.put(("motion_done", label, result))
        except Exception as e:
            tb = traceback.format_exc()
            self._log_q.put(f"[motion] EXCEPTION: {e}")
            self._result_q.put(("motion_err", label, (str(e), tb)))

    def _redetect_pose_for_phase2(self, target_class, session_dir):
        """2차 탐지 포인트 도달 후 사물 재탐지 — **안정성 게이트 적용**.

        gates:
          - YOLO conf ≥ 0.7 (REDETECT_CONF_MIN, self.yolo.conf 임시 override)
          - bbox centroid 일관성 (drift ≤ 40px) — 같은 사물을 계속 보는지 검증
          - PCA 결과의 base-frame z ≤ 450mm — 그 위면 오탐지 (카메라보다 위에 사물 없음)
          - 위 게이트를 모두 통과하는 detection 이 2.0s 동안 연속 누적되어야 통과
          - 한번이라도 깨지면 누적 history 리셋 → 처음부터 다시

        timeout (TOTAL_TIMEOUT_S=12s) 내에 안정 통과 못하면 None 반환 → motion abort.
        """
        REDETECT_CONF_MIN          = 0.70
        STABLE_DURATION_S          = 2.0
        BBOX_CENTROID_TOLERANCE_PX = 40.0
        Z_BASE_MAX_MM              = 450.0
        DETECT_INTERVAL_S          = 0.15
        TOTAL_TIMEOUT_S            = 12.0
        MIN_SAMPLES                = 5

        saved_conf = self.yolo.conf
        self.yolo.conf = REDETECT_CONF_MIN
        self._log_q.put(
            f"[2차 탐지] yolo.conf 임시 override: {saved_conf:.2f} → {REDETECT_CONF_MIN:.2f}  "
            f"(stable {STABLE_DURATION_S:.1f}s + z≤{Z_BASE_MAX_MM:.0f}mm 게이트)")

        try:
            self.after(0, lambda: self._set_stage(0, "🌀",
                f"[2차 탐지] 안정 탐지 대기 (conf≥{REDETECT_CONF_MIN:.2f}, {STABLE_DURATION_S:.0f}s)"))
            # ★ rclpy.spin_once 호출 금지 ★ — img_node 는 self.executor 에서 spin 중.
            # 진동 정착
            time.sleep(1.0)
            last_stamp = self.img_node.get_color_frame_stamp()
            self._log_q.put(f"[2차 탐지] settle 1.0s 후 polling 시작 (stamp={last_stamp})")

            # 안정 누적 — 게이트 통과한 sample list
            stable_history = []   # [(t, det, new_pose, color, depth, intr, mask, z_base_mm), ...]
            first_centroid = None
            last_detect_time = 0.0
            t_start = time.perf_counter()

            def _reset(reason):
                nonlocal first_centroid
                if stable_history:
                    self._log_q.put(
                        f"[2차 탐지] 안정 카운터 리셋 ({len(stable_history)} → 0): {reason}")
                stable_history.clear()
                first_centroid = None

            while time.perf_counter() - t_start < TOTAL_TIMEOUT_S:
                # fresh frame 대기 (stamp 갱신)
                cur_stamp = self.img_node.get_color_frame_stamp()
                if cur_stamp is None or cur_stamp == last_stamp:
                    time.sleep(0.02)
                    continue
                last_stamp = cur_stamp

                # 검출 rate-limit (~150ms 간격)
                now = time.perf_counter()
                if now - last_detect_time < DETECT_INTERVAL_S:
                    continue
                last_detect_time = now

                color = self.img_node.get_color_frame()
                depth = self.img_node.get_depth_frame()
                intr  = self.img_node.get_camera_intrinsic()
                if color is None or depth is None or intr is None:
                    continue

                det = self.yolo.detect_best(color, target_class)
                if det is None:
                    _reset(f"YOLO 미탐지 (conf<{REDETECT_CONF_MIN:.2f}, '{target_class}')")
                    continue

                x1, y1, x2, y2 = det.box_xyxy
                cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0

                # bbox 일관성 — 첫 detection 의 centroid 와 비교
                if first_centroid is not None:
                    drift = ((cx - first_centroid[0]) ** 2
                             + (cy - first_centroid[1]) ** 2) ** 0.5
                    if drift > BBOX_CENTROID_TOLERANCE_PX:
                        first_centroid = (cx, cy)
                        _reset(f"bbox drift {drift:.1f}px > {BBOX_CENTROID_TOLERANCE_PX:.0f}")
                        continue
                else:
                    first_centroid = (cx, cy)

                # depth ROI + PCA
                mask = filter_depth_roi(depth, det.box_xyxy, median_band_mm=50.0)
                if mask is None:
                    _reset("depth ROI 필터 실패")
                    continue
                pts = deproject_mask(depth, mask, intr, max_points=4000)

                bbox_pts = None
                if det.class_name.strip().lower() == "plate":
                    bbox_mask = filter_depth_roi(depth, det.box_xyxy, median_band_mm=80.0)
                    if bbox_mask is not None:
                        bbox_pts = deproject_mask(depth, bbox_mask, intr, max_points=4000)

                new_pose = compute_grasp_pose(
                    pts, normal_points=bbox_pts, target_class=det.class_name)
                if new_pose is None:
                    _reset("PCA 재계산 실패")
                    continue

                # ★ 오탐지 게이트: base-frame z 검증 ★
                # z > 450mm 면 카메라보다 위 = 워크벤치 사물 위치로 불가능
                try:
                    base2g = self.motion._current_base2gripper()
                    base_pose = cam_pose_to_base_pose(
                        new_pose.position, new_pose.rotation,
                        self.motion.T_gripper2cam, base2g)
                    z_base_mm = float(base_pose[2])
                except Exception as e:
                    _reset(f"base 변환 실패: {e}")
                    continue
                if z_base_mm > Z_BASE_MAX_MM:
                    _reset(f"base z={z_base_mm:.1f}mm > {Z_BASE_MAX_MM:.0f}mm (오탐지)")
                    continue

                # 게이트 통과 — 누적
                stable_history.append(
                    (now, det, new_pose, color, depth, intr, mask, z_base_mm))
                elapsed = stable_history[-1][0] - stable_history[0][0]
                self._log_q.put(
                    f"[2차 탐지] sample#{len(stable_history)}  "
                    f"conf={det.score:.2f}  z_base={z_base_mm:.1f}mm  "
                    f"안정구간 {elapsed:.2f}/{STABLE_DURATION_S:.1f}s")
                self.after(0, lambda n=len(stable_history), e=elapsed:
                    self._set_stage(0, "🌀",
                        f"[2차 탐지] 안정 {e:.1f}/{STABLE_DURATION_S:.1f}s  ({n} samples)"))

                if elapsed >= STABLE_DURATION_S and len(stable_history) >= MIN_SAMPLES:
                    self._log_q.put(
                        f"[2차 탐지] ✓ 안정 통과  ({STABLE_DURATION_S:.1f}s, "
                        f"{len(stable_history)} samples)")
                    break

            # timeout 체크
            if (not stable_history
                    or stable_history[-1][0] - stable_history[0][0] < STABLE_DURATION_S
                    or len(stable_history) < MIN_SAMPLES):
                self._log_q.put(
                    f"[2차 탐지] ✗ 안정 탐지 실패 (timeout {TOTAL_TIMEOUT_S:.0f}s, "
                    f"samples={len(stable_history)})")
                self.after(0, lambda: self._set_stage(0, "✗", "[2차] 안정 탐지 실패"))
                return None

            # 가장 최근 sample 채택
            _, det, new_pose, color, depth, intr, mask, z_base_mm = stable_history[-1]
            self._log_q.put(
                f"[2차 탐지] 채택  bbox={det.box_xyxy}  score={det.score:.2f}  "
                f"z_base={z_base_mm:.1f}mm  mode={new_pose.grasp_mode}  "
                f"q={new_pose.quality:.2f}")
            self.after(0, lambda d=det: self._set_stage(0, "✓",
                f"[2차] {d.class_name} (conf {d.score:.2f}, 안정)"))
            self.after(0, lambda p=new_pose: self._set_stage(3, "✓",
                f"[2차] mode={p.grasp_mode}  q={p.quality:.2f}"))

            # 워크벤치 plane → 동적 approach_offset 재갱신
            APPROACH_OFFSET_CAP_MM = 80.0
            wb = estimate_workbench_plane(depth, det.box_xyxy, intr, pad_px=80)
            if wb is not None:
                wb_centroid_m, wb_normal = wb
                obj_height_m = perpendicular_distance(
                    new_pose.position, wb_centroid_m, wb_normal)
                obj_height_mm = obj_height_m * 1000.0
                dyn_offset_mm = max(0.0, min(obj_height_mm / 2.0 + 20.0,
                                             APPROACH_OFFSET_CAP_MM))
                self.motion.approach_offset_mm = dyn_offset_mm
                self._log_q.put(
                    f"[2차 탐지] workbench plane OK  obj_height={obj_height_mm:.1f}mm "
                    f"→ approach_offset={dyn_offset_mm:.1f}mm "
                    f"(cap={APPROACH_OFFSET_CAP_MM:.0f})")
                self.after(0, lambda h=obj_height_mm, d=dyn_offset_mm:
                    (self._set_stage(4, "✓", f"[2차] obj_h={h:.1f}mm"),
                     self._set_stage(5, "✓", f"[2차] offset={d:.1f}mm")))
            else:
                self._log_q.put(
                    f"[2차 탐지] workbench plane 추정 실패 — "
                    f"approach_offset 유지 ({self.motion.approach_offset_mm:.1f}mm)")
                self.after(0, lambda: (
                    self._set_stage(4, "⚠", "[2차] workbench 실패"),
                    self._set_stage(5, "⚠", "[2차] offset 유지")))

            # GUI 패널 갱신 (메인 스레드 안전)
            self.after(0, lambda c=color, d=depth, i=intr, dt=det,
                       p=new_pose, m=mask: self._update_phase2_panels(c, d, i, dt, p, m))

            # 진단 스냅샷
            if session_dir is not None:
                try:
                    annotated = color.copy()
                    x1, y1, x2, y2 = det.box_xyxy
                    cv2.rectangle(annotated, (x1, y1), (x2, y2), (102, 230, 76), 2)
                    cv2.putText(annotated,
                                f"P2 {det.class_name} {det.score:.2f}",
                                (x1, max(0, y1 - 6)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1)
                    cv2.imwrite(str(session_dir / "10_phase2_redetect.jpg"),
                                annotated)
                except Exception as e:
                    self._log_q.put(f"[2차 탐지] snapshot 실패: {e}")

            return new_pose
        except Exception as e:
            tb = traceback.format_exc()
            self._log_q.put(f"[2차 탐지] EXCEPTION: {e}")
            for ln in tb.splitlines()[-6:]:
                self._log_q.put(f"  {ln}")
            return None
        finally:
            self.yolo.conf = saved_conf
            self._log_q.put(f"[2차 탐지] yolo.conf 복원: {self.yolo.conf:.2f}")

    def _update_phase2_panels(self, color, depth, intr, det, pose, mask):
        """2차 탐지 결과를 GUI 패널 ① ② ③ ④ 에 반영.

        반드시 메인 스레드에서 호출 (self.after 로 스케줄됨).
        """
        try:
            # ① crop (2차 detection)
            crop = crop_bbox(color, det.box_xyxy, pad=8)
            self._show_canvas(self.crop_canvas, crop)

            # ② annotated (bbox + approach + principal + tilt label)
            annotated = color.copy()
            self._draw_dets_on(annotated, [det])
            x1, y1, x2, y2 = det.box_xyxy
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 0, 255), 2)
            try:
                self._draw_approach_arrow(annotated, pose, intr)
                self._draw_principal_axis(annotated, pose, intr)
                self._draw_angle_label(annotated, pose, intr)
            except Exception as e:
                self._log_q.put(f"[2차 탐지] annotation 그리기 실패: {e}")
            # ② 패널은 객체 주변만 잘라서 표시
            pad = 30
            H, W = annotated.shape[:2]
            view = annotated[max(0, y1-pad):min(H, y2+pad),
                             max(0, x1-pad):min(W, x2+pad)]
            if view.size == 0:
                view = annotated
            self._show_canvas(self.roi_canvas, view)

            # ③ depth heatmap (jet)
            depth_roi = depth[y1:y2, x1:x2].copy()
            mask_roi = mask[y1:y2, x1:x2] if mask is not None else None
            heatmap = depth_to_heatmap(depth_roi, mask_roi)
            if mask_roi is not None:
                cnts, _ = cv2.findContours(mask_roi.astype(np.uint8) * 255,
                                           cv2.RETR_EXTERNAL,
                                           cv2.CHAIN_APPROX_SIMPLE)
                cv2.drawContours(heatmap, cnts, -1, (255, 255, 255), 1)
            self._show_canvas(self.depth_canvas, heatmap)

            # ④ info text — 2차 탐지 결과로 교체
            info = self._fmt_info_phase2(det, pose)
            self._info_set(info)
        except Exception as e:
            self._log_q.put(f"[2차 탐지] 패널 갱신 실패: {e}")
            for ln in traceback.format_exc().splitlines()[-4:]:
                self._log_q.put(f"  {ln}")

    def _fmt_info_phase2(self, det, pose):
        """2차 탐지 결과 info text — 1차 fmt 보다 간결, 핵심 메트릭만."""
        approach = pose.rotation[:, 2]
        principal = pose.axes[:, 0]
        x1, y1, x2, y2 = det.box_xyxy
        mode_tag = {
            "radial":      "방사형 (plate)",
            "cylindrical": "원통/길쭉 (banana)",
            "spherical":   "구체 (그 외)",
        }.get(pose.grasp_mode, pose.grasp_mode or "unknown")
        return "\n".join([
            "Status:     ★ PHASE 2 ANALYSIS DONE ★",
            f"(2차 탐지 — z=450 위에서 재계산)",
            "",
            f"Class:      {det.class_name}  (conf {det.score:.2f})",
            f"Mode:       {pose.grasp_mode}  — {mode_tag}",
            f"BBox:       [{x1}, {y1}, {x2}, {y2}]",
            "",
            "── PCA 진단 (재계산) ──",
            f"PointCloud: roi={pose.n_points_centroid}  normal={pose.n_points_normal}",
            f"eigvals:    [{pose.eigvals[0]:.4f}, {pose.eigvals[1]:.4f}, "
            f"{pose.eigvals[2]:.4f}]",
            f"linearity:  {pose.linearity:.2f}",
            f"planarity:  {pose.planarity:.2f}",
            f"quality:    {pose.quality:.2f}",
            "",
            "── 그리퍼 자세 (재계산) ──",
            f"Width:      {pose.width*1000:.1f} mm",
            f"Position(m, cam):",
            f"  X={pose.position[0]:+.3f}  Y={pose.position[1]:+.3f}  "
            f"Z={pose.position[2]:+.3f}",
            f"",
            f"Tilt:       {pose.tilt_deg:5.1f} deg",
            f"Azimuth:    {pose.azimuth_deg:+5.1f} deg",
            f"Approach:   [{approach[0]:+.2f}, {approach[1]:+.2f}, "
            f"{approach[2]:+.2f}]",
            f"Principal:  [{principal[0]:+.2f}, {principal[1]:+.2f}, "
            f"{principal[2]:+.2f}]",
            "",
            f"approach_offset:  {self.motion.approach_offset_mm:.1f}mm "
            "(workbench 기반 동적)",
        ])

    def _on_motion_done(self, label, result):
        ok = bool(getattr(result, "success", False))
        self.log(f"=== motion done: success={ok}  "
                 f"msg={getattr(result, 'message', '?')} ===")
        self.status_var.set(
            ("✓ 모션 완료" if ok else "✗ 모션 실패")
            + f" — {label}  width={getattr(result, 'width_mm', 0):.1f}mm")
        self._set_stage(7, "✓" if ok else "✗",
                        getattr(result, "message", "?"))
        self.busy = False

    # ─── Scan Point 버튼 ──────────────────────
    SCAN_POINT_JOINT_DEG = [-3.65, -0.35, 59.37, 0.0, 109.0, -2.5]

    def _on_scan_point_clicked(self):
        if self.busy:
            self.log("처리 중 — Scan Point 버튼 무시")
            return
        if not self.execute_motion:
            messagebox.showinfo("Scan Point 비활성",
                                "--no-execute 모드에선 모션 비활성화됨", parent=self)
            return
        ok = messagebox.askyesno(
            "Scan Point 이동 확인",
            f"로봇을 스캔 자세 {self.SCAN_POINT_JOINT_DEG}° 로 이동합니다.\n\n"
            "  - movej (관절 공간) — singularity 안전\n"
            "  - 그리퍼 자동 open\n"
            "  - vel/acc = 30°/s\n\n"
            "주변 안전 거리 확인 후 진행하시겠습니까?",
            parent=self)
        if not ok:
            self.log("Scan Point 취소")
            return
        self.busy = True
        self.status_var.set("Scan Point 이동 중...")
        self.log(f"=== scan_point start (joint={self.SCAN_POINT_JOINT_DEG}) ===")
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        """Scan Point joint 이동 — _home_worker 와 동일한 setup 패턴."""
        try:
            if not self._dsr_setup_done:
                self._log_q.put("[motion] DSR client node 생성 중...")
                from rclpy.node import Node as _RclNode
                self._dsr_node = _RclNode("grasp_gui_dsr_client",
                                          namespace="dsr01")
                setup_dsr(self._dsr_node)
                self._dsr_setup_done = True
            if self.motion is None:
                self._log_q.put("[motion] DoosanGripperMotion 초기화 (scan용)")
                self.motion = DoosanGripperMotion(
                    dryrun=False,
                    gripper_type=self.gripper_type,
                    gripper_ip=self.gripper_ip,
                    gripper_port=self.gripper_port,
                    approach_offset_mm=self.approach_offset_mm,
                    logger=lambda m: self._log_q.put(m))
            self._log_q.put(
                f"[motion] move_to_joint({self.SCAN_POINT_JOINT_DEG}, label='scan_point')")
            result = self.motion.move_to_joint(
                self.SCAN_POINT_JOINT_DEG, vel_deg=30.0, acc_deg=30.0,
                label="scan_point")
            self._result_q.put(("motion_done", "SCAN_POINT", result))
        except Exception as e:
            tb = traceback.format_exc()
            self._log_q.put(f"[motion] SCAN_POINT EXCEPTION: {e}")
            self._result_q.put(("motion_err", "SCAN_POINT", (str(e), tb)))

    # ─── 홈 버튼 ─────────────────────────────
    def _on_home_clicked(self):
        if self.busy:
            self.log("처리 중 — Home 버튼 무시")
            return
        if not self.execute_motion:
            messagebox.showinfo("Home 비활성",
                                "--no-execute 모드에선 모션 비활성화됨", parent=self)
            return
        ok = messagebox.askyesno(
            "Home 이동 확인",
            "로봇을 홈 자세 [0, 0, 90, 0, 90, 0]° 로 이동합니다.\n\n"
            "  - movej (관절 공간) — singularity 안전\n"
            "  - 그리퍼 자동 open\n"
            "  - vel/acc = 30°/s\n\n"
            "주변 안전 거리 확인 후 진행하시겠습니까?",
            parent=self)
        if not ok:
            self.log("Home 취소")
            return
        self.busy = True
        self.status_var.set("홈 이동 중...")
        self.log("=== home start ===")
        threading.Thread(target=self._home_worker, daemon=True).start()

    def _home_worker(self):
        """별도 스레드에서 home 이동. _motion_worker 와 동일한 setup 재사용."""
        try:
            if not self._dsr_setup_done:
                self._log_q.put("[motion] DSR client node 생성 중...")
                from rclpy.node import Node as _RclNode
                self._dsr_node = _RclNode("grasp_gui_dsr_client",
                                          namespace="dsr01")
                self._log_q.put(
                    f"[motion] DSR node='{self._dsr_node.get_name()}' "
                    f"namespace='{self._dsr_node.get_namespace()}'")
                setup_dsr(self._dsr_node)
                self._dsr_setup_done = True
            if self.motion is None:
                self._log_q.put(
                    f"[motion] DoosanGripperMotion 초기화 (home용)")
                self.motion = DoosanGripperMotion(
                    dryrun=False,
                    gripper_type=self.gripper_type,
                    gripper_ip=self.gripper_ip,
                    gripper_port=self.gripper_port,
                    approach_offset_mm=self.approach_offset_mm,
                    logger=lambda m: self._log_q.put(m))
            self._log_q.put("[motion] move_home() 호출")
            result = self.motion.move_home()
            self._result_q.put(("motion_done", "HOME", result))
        except Exception as e:
            tb = traceback.format_exc()
            self._log_q.put(f"[motion] HOME EXCEPTION: {e}")
            self._result_q.put(("motion_err", "HOME", (str(e), tb)))

    def _on_motion_err(self, label, payload):
        msg, tb = payload
        self.log(f"=== motion ERROR: {msg} ===")
        for ln in tb.splitlines()[-8:]:
            self.log(f"  {ln}")
        self.status_var.set(f"✗ 모션 예외 — {label}: {msg[:60]}")
        self._set_stage(7, "✗", f"예외: {msg[:50]}")
        self.busy = False

    def _reset(self):
        if self.busy:
            self.log("처리 중 — Reset 보류")
            return
        for c in (self.crop_canvas, self.roi_canvas, self.depth_canvas):
            c.delete("all")
        self._info_set("Status: IDLE\n라이브 뷰의 bbox 를 클릭하세요\n")
        self._init_stages()
        self.status_var.set("IDLE")
        self.log("Reset")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", type=Path, default=None)
    ap.add_argument("--device", default="0")
    ap.add_argument("--vlm-model", default="gpt-4o")
    # 모션 실행 옵션 (기본 ON — bbox 클릭 → 확인 → 실 로봇 동작)
    # perception 만 검증하려면 --no-execute 로 끄기
    ap.add_argument("--execute", action=argparse.BooleanOptionalAction, default=True,
                    help="bbox 클릭 → pose 계산 후 실 로봇 모션 실행 (확인 팝업 후). "
                         "기본 ON. 검증만 할 때는 --no-execute")
    ap.add_argument("--gripper-type", default="rg2", choices=["rg2", "rg6"])
    ap.add_argument("--gripper-ip", default="192.168.1.1",
                    help="OnRobot Compute Box IP (기본 192.168.1.1, "
                         "비활성하려면 명시적으로 빈 문자열 또는 --no-execute)")
    ap.add_argument("--gripper-port", type=int, default=502)
    ap.add_argument("--quality-min", type=float, default=0.5)
    ap.add_argument("--planarity-min", type=float, default=0.3)
    ap.add_argument("--non-planarity-max", type=float, default=0.10,
                    help="sqrt(λ3)/sqrt(λ1) 상한. 0.10=10%% 이하 표면만 통과 "
                         "(bowl/dish 같은 굴곡 표면 자동 거부)")
    ap.add_argument("--approach-offset-mm", type=float, default=50.0,
                    help="approach 방향 진입 깊이 보정. "
                         "양수=centroid 안쪽으로 더 진입, 음수=후퇴, 0=비활성. 기본 +50mm")
    args = ap.parse_args()

    weights = args.weights or YoloDetector.auto_weights_path()
    print(f"[CONFIG] weights={weights}")
    print(f"[CONFIG] device={args.device}  vlm_model={args.vlm_model}")
    print(f"[CONFIG] OPENAI_API_KEY "
          f"{'set' if os.environ.get('OPENAI_API_KEY') else 'MISSING (~/.bashrc 확인)'}")
    print(f"[CONFIG] history dir: {HISTORY_DIR}")
    print(f"[CONFIG] EXECUTE MOTION = {args.execute}  "
          f"(gripper={args.gripper_type}@{args.gripper_ip})")

    app = GraspGUI(weights, args.device, args.vlm_model,
                   execute_motion=args.execute,
                   gripper_type=args.gripper_type,
                   gripper_ip=args.gripper_ip,
                   gripper_port=args.gripper_port,
                   quality_min=args.quality_min,
                   planarity_min=args.planarity_min,
                   non_planarity_max=args.non_planarity_max,
                   approach_offset_mm=args.approach_offset_mm)
    app.mainloop()


if __name__ == "__main__":
    main()
