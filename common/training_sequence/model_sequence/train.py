"""train.py — train.ipynb 의 학습 부분만 추출.

데이터 수집(Roboflow 다운로드)·시각화·오류분석은 제외했고,
YAML 생성 → 데이터 검증 → 학습 → 평가/레지스트리 등록만 수행한다.

사용:
  python3 train.py                  # HYPER 기본값 (epochs=100)
  python3 train.py --epochs 3       # 빠른 확인용
  python3 train.py --mode resume --resume-run v1_cobot_0504_1700
  python3 train.py --mode more_data
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
import warnings
from collections import Counter
from datetime import datetime
from pathlib import Path

# ── 로그 억제 (import 전에 설정해야 효과) ───────────────────────────────────
os.environ.setdefault("YOLO_VERBOSE", "False")
warnings.filterwarnings("ignore")

import cv2
import pandas as pd
import torch
import yaml
from ultralytics import YOLO
from ultralytics.utils import LOGGER as _UL_LOGGER

# Ultralytics 로거: WARNING 만 (Freezing layer / per-batch table 등 제거)
_UL_LOGGER.setLevel(logging.WARNING)

# ── 경로 ──────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).resolve().parent
DATA_DIR    = Path("/home/rokey/cobot_ws/src/donttouch/training_sequence/data")   # 7-class 통합 데이터셋
RUNS_DIR    = BASE_DIR / "runs"
VERS_DIR    = BASE_DIR / "versions"
LOGS_DIR    = BASE_DIR / "logs"
YAML_PATH   = BASE_DIR / "cobot.yaml"
REGISTRY    = BASE_DIR / "model_registry.json"
OD_RESOURCE = Path("/home/rokey/cobot_ws/src/cobot2/object_detection/resource")


# ── stdout/stderr → 파일 동시 기록 (tee) ─────────────────────────────────
class _Tee:
    """sys.stdout/sys.stderr 를 콘솔 + 로그파일에 동시 출력."""
    def __init__(self, *streams):
        self.streams = streams
    def write(self, data):
        for s in self.streams:
            try:
                s.write(data); s.flush()
            except Exception:
                pass
    def flush(self):
        for s in self.streams:
            try: s.flush()
            except Exception: pass
    def isatty(self):  # tqdm 등이 묻는 경우
        return getattr(self.streams[0], "isatty", lambda: False)()


def setup_log_file() -> Path:
    """logs/train_<ts>.log 생성 + sys.stdout/stderr 를 tee 로 교체."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"train_{datetime.now():%Y%m%d_%H%M%S}.log"
    log_fp = open(log_path, "w", encoding="utf-8", buffering=1)  # line-buffered
    sys.stdout = _Tee(sys.__stdout__, log_fp)
    sys.stderr = _Tee(sys.__stderr__, log_fp)
    # ultralytics 로거에도 FileHandler 추가 (그들의 내부 INFO/WARN 캡처)
    fh = logging.FileHandler(str(log_path), encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter("[%(asctime)s] %(name)s: %(message)s",
                                       datefmt="%H:%M:%S"))
    _UL_LOGGER.addHandler(fh)
    return log_path

CLASS_NAMES = ["shaker", "toy_block", "plate",
               "apple", "pear", "orange", "banana"]


# ── ModelRegistry ─────────────────────────────────────────────────────────
class ModelRegistry:
    """버전 관리 + 성능 기록 + best.pt 자동 갱신.

    best 기준 = fitness (= 0.1·mAP50 + 0.9·mAP50-95). YOLO 내부와 동일.
    """

    def __init__(self, registry_path: Path, versions_dir: Path):
        self.path = registry_path
        self.versions_dir = versions_dir
        versions_dir.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {"versions": [], "best_version": None, "best_fitness": 0.0}

    def _save(self):
        self.path.write_text(json.dumps(self._data, indent=2, ensure_ascii=False))

    @staticmethod
    def fitness(metrics: dict) -> float:
        return 0.1 * metrics.get("map50", 0.0) + 0.9 * metrics.get("map5095", 0.0)

    @staticmethod
    def env_snapshot() -> dict:
        env = {"python": sys.version.split()[0], "platform": platform.platform()}
        try:
            env["torch"] = torch.__version__
            env["cuda"] = torch.version.cuda or "cpu"
        except Exception:
            pass
        try:
            import ultralytics
            env["ultralytics"] = ultralytics.__version__
        except Exception:
            pass
        return env

    @staticmethod
    def git_commit() -> str:
        try:
            return subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(BASE_DIR), stderr=subprocess.DEVNULL,
            ).decode().strip()
        except Exception:
            return "none"

    def next_version(self) -> str:
        return f"v{len(self._data['versions']) + 1}"

    def make_run_name(self, version: str) -> str:
        return f"{version}_cobot_{datetime.now().strftime('%m%d_%H%M')}"

    @staticmethod
    def data_fingerprint(data_dir: Path) -> dict:
        fp = {}
        for split in ["train", "valid", "test"]:
            img_dir = data_dir / "images" / split
            files = sorted(p.name for p in img_dir.glob("*.[jp][pn]g")) if img_dir.exists() else []
            fp[f"{split}_count"] = len(files)
            fp[f"{split}_hash"] = hashlib.md5("\n".join(files).encode()).hexdigest()[:8]
        return fp

    def detect_data_change(self, current_fp: dict) -> tuple[bool, str]:
        if not self._data["versions"]:
            return False, "최초 학습"
        last_fp = self._data["versions"][-1].get("data_fingerprint", {})
        if not last_fp:
            return False, "이전 fingerprint 없음"
        changes = []
        for split in ["train", "valid", "test"]:
            oc, nc = last_fp.get(f"{split}_count", 0), current_fp.get(f"{split}_count", 0)
            oh, nh = last_fp.get(f"{split}_hash", ""), current_fp.get(f"{split}_hash", "")
            if oc != nc:
                changes.append(f"{split}: {oc}→{nc}장 (+{nc-oc})")
            elif oh != nh:
                changes.append(f"{split}: 파일 교체됨")
        return (True, " / ".join(changes)) if changes else (False, "변경 없음")

    def list_checkpoints(self, runs_dir: Path) -> list[dict]:
        result = []
        for last_pt in sorted(runs_dir.glob("*/weights/last.pt"),
                              key=lambda p: p.stat().st_mtime, reverse=True):
            run_name = last_pt.parent.parent.name
            best_pt  = last_pt.parent / "best.pt"
            csv_path = last_pt.parent.parent / "results.csv"
            epoch = "?"
            if csv_path.exists():
                try:
                    epoch = str(len(pd.read_csv(csv_path)))
                except Exception:
                    pass
            result.append({
                "run_name": run_name, "last_pt": str(last_pt),
                "has_best": best_pt.exists(), "epochs_done": epoch,
                "mtime": datetime.fromtimestamp(last_pt.stat().st_mtime).strftime("%m/%d %H:%M"),
            })
        return result

    def register(self, version, run_name, train_mode, base_model, checkpoint_src,
                 hyper, data_counts, data_fingerprint, src_pt, metrics) -> dict:
        versioned_pt = self.versions_dir / f"{run_name}.pt"
        shutil.copy2(src_pt, versioned_pt)
        score = metrics.get("fitness", self.fitness(metrics))
        metrics["fitness"] = round(float(score), 4)
        prev_best = self._data.get("best_fitness", 0.0)
        is_best = score > prev_best
        entry = {
            "version": version, "run_name": run_name,
            "timestamp": datetime.now().isoformat(),
            "train_mode": train_mode, "model_arch": "yolov8s",
            "base_model": base_model, "checkpoint_src": checkpoint_src,
            "git_commit": self.git_commit(), "env": self.env_snapshot(),
            "hyper": hyper, "data": data_counts, "data_fingerprint": data_fingerprint,
            "metrics": metrics, "pt_file": str(versioned_pt.relative_to(BASE_DIR)),
            "is_best": is_best,
        }
        if is_best:
            for v in self._data["versions"]:
                v["is_best"] = False
            self._data["best_version"] = version
            self._data["best_fitness"] = round(score, 4)
        self._data["versions"].append(entry)
        self._save()
        return entry

    def best_pt_path(self) -> Path | None:
        bv = self._data.get("best_version")
        if bv is None:
            return None
        for v in self._data["versions"]:
            if v["version"] == bv:
                return BASE_DIR / v["pt_file"]
        return None


# ── 데이터 검증 ────────────────────────────────────────────────────────────
def validate_split(split: str) -> dict:
    img_dir = DATA_DIR / "images" / split
    lbl_dir = DATA_DIR / "labels" / split
    imgs = sorted(img_dir.glob("*.[jp][pn]g"))
    counter, no_lbl, bad_ann = Counter(), [], []
    for img in imgs:
        lbl = lbl_dir / (img.stem + ".txt")
        if not lbl.exists():
            no_lbl.append(img.name)
            continue
        for line in lbl.read_text().strip().splitlines():
            parts = line.split()
            if len(parts) != 5:
                bad_ann.append(img.name)
                break
            cls_id = int(parts[0])
            if 0 <= cls_id < len(CLASS_NAMES):
                counter[CLASS_NAMES[cls_id]] += 1
    lbls = sorted(lbl_dir.glob("*.txt"))
    return {"n_img": len(imgs), "n_lbl": len(lbls), "counter": counter,
            "no_lbl": no_lbl, "bad_ann": bad_ann}


# ── 메트릭 시각화 ───────────────────────────────────────────────────────────
def save_metrics_visualization(out_dir: Path, version: str, run_name: str,
                               metrics: dict, per_class_ap: dict,
                               n_train: int, n_valid: int, n_test: int):
    """학습 결과 한 장 요약 + per-class AP 막대그래프 저장.

    out_dir/
      ├── metrics_summary.png   (전체 요약)
      └── per_class_ap.png      (클래스별 AP 바)
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    out_dir.mkdir(parents=True, exist_ok=True)

    # ── per_class_ap.png ──
    classes = sorted(per_class_ap.keys(), key=lambda k: -per_class_ap[k])
    aps = [per_class_ap[c] for c in classes]
    colors = ["#4caf50" if a >= 0.7 else "#ffb300" if a >= 0.5 else "#e53935"
              for a in aps]
    fig, ax = plt.subplots(figsize=(9, max(3, 0.45 * len(classes) + 1.5)))
    bars = ax.barh(classes, aps, color=colors, edgecolor="#333", linewidth=0.6)
    ax.set_xlim(0, 1.0)
    ax.invert_yaxis()
    ax.set_xlabel("AP@50")
    ax.set_title(f"Per-class AP@50  —  {run_name}", fontsize=11)
    ax.axvline(0.5, color="#e53935", linestyle="--", linewidth=0.8, alpha=0.5)
    ax.axvline(0.7, color="#ffb300", linestyle="--", linewidth=0.8, alpha=0.5)
    ax.axvline(0.9, color="#4caf50", linestyle="--", linewidth=0.8, alpha=0.5)
    for bar, ap in zip(bars, aps):
        ax.text(ap + 0.01, bar.get_y() + bar.get_height() / 2,
                f"{ap:.3f}", va="center", fontsize=9)
    ax.grid(axis="x", linestyle=":", alpha=0.4)
    fig.tight_layout()
    fig.savefig(out_dir / "per_class_ap.png", dpi=130)
    plt.close(fig)

    # ── metrics_summary.png ──
    fig = plt.figure(figsize=(11, 7.5))
    gs = fig.add_gridspec(3, 2, height_ratios=[0.7, 1.4, 1.4],
                          hspace=0.45, wspace=0.25)

    # 헤더 (텍스트)
    ax0 = fig.add_subplot(gs[0, :])
    ax0.axis("off")
    head = (f"{version}  ·  {run_name}\n"
            f"data: train={n_train}  valid={n_valid}  test={n_test}  "
            f"·  classes={len(per_class_ap)}")
    ax0.text(0.0, 0.7, head, fontsize=12, fontweight="bold", va="top")
    ax0.text(0.0, 0.0,
             f"★ fitness={metrics['fitness']:.4f}    "
             f"FPS={metrics['fps']:.1f}    "
             f"center_err={metrics.get('center_err_px', 0):.1f}px "
             f"(n={metrics.get('center_matches', 0)})",
             fontsize=11, va="bottom", color="#444")

    # 좌하: 핵심 지표 바
    ax1 = fig.add_subplot(gs[1, 0])
    keys = ["mAP@50", "mAP@50-95", "Precision", "Recall", "F1"]
    vals = [metrics["map50"], metrics["map5095"],
            metrics["precision"], metrics["recall"], metrics["f1"]]
    bars = ax1.bar(keys, vals, color=["#1976d2", "#0d47a1",
                                       "#7b1fa2", "#388e3c", "#5d4037"])
    ax1.set_ylim(0, 1.0)
    ax1.set_title("Detection metrics (test split)", fontsize=10)
    ax1.grid(axis="y", linestyle=":", alpha=0.4)
    for b, v in zip(bars, vals):
        ax1.text(b.get_x() + b.get_width() / 2, v + 0.015,
                 f"{v:.3f}", ha="center", fontsize=9)

    # 우하: per-class AP 가로 바
    ax2 = fig.add_subplot(gs[1, 1])
    pc_classes = sorted(per_class_ap.keys(), key=lambda k: -per_class_ap[k])
    pc_aps = [per_class_ap[c] for c in pc_classes]
    pc_colors = ["#4caf50" if a >= 0.7 else "#ffb300" if a >= 0.5 else "#e53935"
                 for a in pc_aps]
    bars = ax2.barh(pc_classes, pc_aps, color=pc_colors,
                    edgecolor="#333", linewidth=0.5)
    ax2.set_xlim(0, 1.0)
    ax2.invert_yaxis()
    ax2.set_title("Per-class AP@50", fontsize=10)
    ax2.axvline(0.5, color="#e53935", linestyle="--", linewidth=0.7, alpha=0.5)
    ax2.axvline(0.7, color="#ffb300", linestyle="--", linewidth=0.7, alpha=0.5)
    ax2.grid(axis="x", linestyle=":", alpha=0.4)
    for b, a in zip(bars, pc_aps):
        ax2.text(a + 0.015, b.get_y() + b.get_height() / 2,
                 f"{a:.2f}", va="center", fontsize=8)

    # 하단: 텍스트 요약 (json-like)
    ax3 = fig.add_subplot(gs[2, :])
    ax3.axis("off")
    weak = [c for c, a in per_class_ap.items() if a < 0.5]
    mid = [c for c, a in per_class_ap.items() if 0.5 <= a < 0.7]
    strong = [c for c, a in per_class_ap.items() if a >= 0.7]
    text = (
        f"강함 (≥0.70):  {', '.join(strong) if strong else '—'}\n"
        f"보통 (0.50~0.70):  {', '.join(mid) if mid else '—'}\n"
        f"약함 (<0.50):  {', '.join(weak) if weak else '—'}"
    )
    ax3.text(0.0, 0.95, text, fontsize=10, va="top", family="monospace",
             color="#222")

    fig.suptitle(f"Training Result Summary  —  {run_name}",
                 fontsize=13, fontweight="bold", y=0.985)
    fig.savefig(out_dir / "metrics_summary.png", dpi=130, bbox_inches="tight")
    plt.close(fig)


# ── center-error (로봇 파지 직결 지표) ─────────────────────────────────────
def compute_center_error(model, imgs_dir: Path, labels_dir: Path,
                         conf: float = 0.25) -> tuple[float, int]:
    errs = []
    for img_path in sorted(imgs_dir.glob("*.[jp][pn]g")):
        lbl_path = labels_dir / f"{img_path.stem}.txt"
        if not lbl_path.exists():
            continue
        img = cv2.imread(str(img_path))
        if img is None:
            continue
        H, W = img.shape[:2]
        gts = []
        for line in lbl_path.read_text().strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split()
            cls = int(parts[0])
            cx, cy = float(parts[1]) * W, float(parts[2]) * H
            gts.append((cls, cx, cy))
        if not gts:
            continue
        res = model(img, conf=conf, verbose=False)[0]
        if res.boxes is None or len(res.boxes) == 0:
            continue
        preds = []
        for b in res.boxes:
            x1, y1, x2, y2 = b.xyxy[0].cpu().numpy()
            preds.append((int(b.cls[0]), (x1 + x2) / 2, (y1 + y2) / 2))
        used = set()
        for g_cls, gx, gy in gts:
            best_d, best_i = None, -1
            for i, (p_cls, px, py) in enumerate(preds):
                if i in used or p_cls != g_cls:
                    continue
                d = ((gx - px) ** 2 + (gy - py) ** 2) ** 0.5
                if best_d is None or d < best_d:
                    best_d, best_i = d, i
            if best_i >= 0:
                used.add(best_i)
                errs.append(best_d)
    if not errs:
        return 0.0, 0
    return float(sum(errs) / len(errs)), len(errs)


# ── 메인 ───────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["new", "resume", "more_data"], default="new")
    ap.add_argument("--resume-run", default="", help="resume 시 run 이름")
    ap.add_argument("--more-data-base-pt", default=None)
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--patience", type=int, default=20)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=-1, help="-1 = auto")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--base-model", default="yolo11s.pt",
                    help="기본 yolo11s.pt. 롤백 시 --base-model yolov8s.pt")
    ap.add_argument("--no-eval", action="store_true", help="학습만, 평가/등록 스킵")
    ap.add_argument("--no-log-file", action="store_true",
                    help="logs/train_<ts>.log 자동 저장 비활성")
    args = ap.parse_args()

    log_path = None
    if not args.no_log_file:
        log_path = setup_log_file()

    print("=" * 55)
    if torch.cuda.is_available():
        gpu = torch.cuda.get_device_name(0)
        vram = torch.cuda.get_device_properties(0).total_memory / 1e9
        print(f"  GPU  : {gpu}  VRAM {vram:.1f} GB")
    else:
        print("  GPU  : 없음 — CPU 학습 (매우 느림)")
    print(f"  BASE : {BASE_DIR}")
    if log_path:
        print(f"  LOG  : {log_path}")
    print("=" * 55)

    # ── YAML 생성 ──
    yaml_content = {
        "path": str(DATA_DIR.resolve()),
        "train": "images/train", "val": "images/valid", "test": "images/test",
        "nc": len(CLASS_NAMES), "names": CLASS_NAMES,
    }
    YAML_PATH.write_text(yaml.dump(yaml_content, allow_unicode=True, default_flow_style=False))
    print(f"YAML 저장: {YAML_PATH}")

    # ── 데이터 검증 ──
    print("=" * 60)
    for split in ["train", "valid", "test"]:
        s = validate_split(split)
        ok = s["n_img"] == s["n_lbl"]
        print(f"  [{split}]  images={s['n_img']}  labels={s['n_lbl']}  {'OK' if ok else 'MISMATCH'}")
        if s["no_lbl"]:
            print(f"    [WARN] 라벨 없는 이미지 {len(s['no_lbl'])}개")
        if s["bad_ann"]:
            print(f"    [WARN] 형식 오류 라벨 {len(s['bad_ann'])}개")
    print("=" * 60)

    registry = ModelRegistry(REGISTRY, VERS_DIR)
    print(f"[ModelRegistry] 기존 버전 {len(registry._data['versions'])}개")

    # ── 하이퍼파라미터 ──
    # 7-class · 1089 train (real:fruits:roboflow ≈ 28:28:44 imgs / 58:26:15 bbox)
    # · multi-object real_data (5.96 bbox/img, top-down 로봇 카메라)
    HYPER = {
        "epochs": args.epochs, "patience": args.patience, "batch": args.batch,
        "imgsz": args.imgsz, "workers": args.workers,
        "cache": "ram", "seed": 42, "deterministic": True,
        # transfer learning + small dataset 1089 imgs → 보수적 LR + 강화된 정규화
        "optimizer": "AdamW", "lr0": 0.0005, "lrf": 0.01,
        "weight_decay": 0.001,                    # 0.0005→0.001 (1089장 작은 dataset 정규화 강화)
        "warmup_epochs": 3, "warmup_momentum": 0.8, "cos_lr": True,
        # freeze 10 → 5: 전체 backbone 동결은 real_data (top-down 로봇 view, COCO 와 매우 다른
        # 시점) 적응을 막음. 뒤 절반 backbone 도 학습하도록 완화.
        "freeze": 5,
        # box: 10.0 시도 (v8) → mAP/center_err 악화로 롤백. default(7.5) 유지.
        # 색상 증강: fruits 색 정체성 보존 위해 hsv_s 0.7→0.4
        "hsv_h": 0.015, "hsv_s": 0.4, "hsv_v": 0.4,
        # 기하 증강: top-down 카메라 환경 가정 (shear/perspective 비활성)
        "degrees": 15.0, "translate": 0.1, "scale": 0.5,
        "shear": 0.0, "perspective": 0.0, "flipud": 0.2, "fliplr": 0.5,
        # 합성 증강:
        #   mosaic 1.0 유지 — 작은 dataset 의 다양성 핵심
        #   mixup 0.15→0.05 — real_data multi-object (5.96 bbox/img) 와 합성 시 과도한 복잡도
        #   copy_paste 0.3→0.0 — segmentation mask 부재 → bbox 영역 잘라 붙이면 부정확 합성
        "mosaic": 1.0, "mixup": 0.05, "copy_paste": 0.0, "close_mosaic": 15,
        # erasing 명시화: ultralytics default 0.4 → 0.2 로 완화
        "erasing": 0.2,
        # multi_scale: 카메라 거리 30~50cm 변동 → 객체 크기 다양성 학습
        "multi_scale": True,
        # 정규화: 작은 dataset → mild dropout 추가, label_smoothing 유지
        "label_smoothing": 0.1, "dropout": 0.1,    # dropout 0.0→0.1
        "save_period": 20, "plots": True, "verbose": False, "amp": True,
    }
    print(f"TRAIN_MODE = {args.mode}")
    print(f"epochs={HYPER['epochs']}  patience={HYPER['patience']}  batch={HYPER['batch']}")

    # ── TRAIN_MODE 분기 ──
    current_fp = ModelRegistry.data_fingerprint(DATA_DIR)
    if current_fp["train_count"] == 0:
        raise RuntimeError(f"train 이미지 없음: {DATA_DIR / 'images' / 'train'}")
    if current_fp["valid_count"] == 0:
        raise RuntimeError("valid 이미지 없음")
    data_changed, change_msg = registry.detect_data_change(current_fp)
    print(f"데이터: train={current_fp['train_count']}  valid={current_fp['valid_count']}  test={current_fp['test_count']}")
    print(f"데이터 변경: {change_msg}")

    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    if args.mode == "resume":
        if not args.resume_run:
            raise ValueError("--resume-run 을 지정하세요")
        last_pt = RUNS_DIR / args.resume_run / "weights" / "last.pt"
        if not last_pt.exists():
            raise FileNotFoundError(f"last.pt 없음: {last_pt}")
        VERSION = args.resume_run.split("_")[0]
        RUN_NAME = args.resume_run
        checkpoint_src = str(last_pt)
        model = YOLO(str(last_pt))
        resume_flag = True
        print(f"\n[RESUME] version={VERSION}  from={last_pt}")
    elif args.mode == "more_data":
        base_pt = (Path(args.more_data_base_pt) if args.more_data_base_pt
                   else registry.best_pt_path())
        if base_pt is None or not base_pt.exists():
            raise FileNotFoundError("시작점 PT 없음. 먼저 --mode new 로 학습하세요.")
        VERSION = registry.next_version()
        RUN_NAME = registry.make_run_name(VERSION)
        checkpoint_src = str(base_pt)
        model = YOLO(str(base_pt))
        resume_flag = False
        print(f"\n[MORE_DATA] version={VERSION}  warm-start={base_pt.name}")
    else:
        VERSION = registry.next_version()
        RUN_NAME = registry.make_run_name(VERSION)
        checkpoint_src = args.base_model
        model = YOLO(args.base_model)
        resume_flag = False
        print(f"\n[NEW] version={VERSION}  base={args.base_model}")
    print(f"run_name={RUN_NAME}\n")

    # ── 진행상황 1줄 overwrite 콜백 ────────────────────────────────────────
    train_t0 = [time.time()]

    def on_fit_epoch_end(trainer):
        """매 epoch (train+val 완료 시) 한 줄을 \\r 로 갱신."""
        ep = trainer.epoch + 1
        total = trainer.epochs
        # train loss
        ln = getattr(trainer, "loss_names", None) or ["box", "cls", "dfl"]
        tl = trainer.tloss.detach().cpu().tolist() if hasattr(trainer, "tloss") else []
        loss_s = "  ".join(f"{n}={v:.3f}" for n, v in zip(ln, tl))
        # val metrics
        m = getattr(trainer, "metrics", {}) or {}
        m50 = m.get("metrics/mAP50(B)", 0.0)
        m95 = m.get("metrics/mAP50-95(B)", 0.0)
        # 경과 / 잔여 시간
        elapsed = time.time() - train_t0[0]
        eta = elapsed / ep * (total - ep)
        bar_n = int(30 * ep / total)
        bar = "█" * bar_n + "─" * (30 - bar_n)
        line = (f"\r[{bar}] {ep:>3}/{total}  {loss_s}  "
                f"mAP50={m50:.3f}  mAP50-95={m95:.3f}  "
                f"T+{int(elapsed//60):d}m{int(elapsed%60):02d}s "
                f"ETA {int(eta//60):d}m{int(eta%60):02d}s")
        print(line, end="", flush=True)

    def on_train_end(trainer):
        print()  # 마지막에 줄바꿈

    model.add_callback("on_fit_epoch_end", on_fit_epoch_end)
    model.add_callback("on_train_end", on_train_end)

    # ── 학습 실행 ──
    model.train(
        data=str(YAML_PATH), project=str(RUNS_DIR), name=RUN_NAME,
        resume=resume_flag, exist_ok=(args.mode == "resume"),
        device=0 if torch.cuda.is_available() else "cpu",
        **HYPER,
    )

    TRAINED_PT = RUNS_DIR / RUN_NAME / "weights" / "best.pt"
    if not TRAINED_PT.exists():
        raise FileNotFoundError(f"best.pt 없음: {TRAINED_PT}")
    print(f"\n[학습 완료] best.pt: {TRAINED_PT}")

    if args.no_eval:
        return

    # ── 평가 + 레지스트리 등록 ──
    eval_model = YOLO(str(TRAINED_PT))
    metrics = eval_model.val(
        data=str(YAML_PATH), split="test", imgsz=HYPER["imgsz"], batch=8,
        verbose=False, plots=True,
        project=str(RUNS_DIR), name=f"{RUN_NAME}_test_eval", exist_ok=True,
    )
    box = metrics.box
    mp, mr = float(box.mp), float(box.mr)
    f1 = 2 * mp * mr / (mp + mr + 1e-9)
    per_class_ap = {
        CLASS_NAMES[int(idx)]: round(float(ap), 4)
        for idx, ap in zip(box.ap_class_index, box.ap50)
        if int(idx) < len(CLASS_NAMES)
    }

    test_imgs = sorted((DATA_DIR / "images" / "test").glob("*.[jp][pn]g"))
    if test_imgs:
        sample_imgs = [cv2.imread(str(p)) for p in test_imgs[:5]]
        for _ in range(30):
            eval_model(sample_imgs[0], verbose=False)
        t_list = []
        for i in range(50):
            t0 = time.perf_counter()
            eval_model(sample_imgs[i % len(sample_imgs)], verbose=False)
            t_list.append(time.perf_counter() - t0)
        fps = 1.0 / (sum(t_list) / len(t_list))
    else:
        fps = 0.0

    center_err_px, n_matched = compute_center_error(
        eval_model, DATA_DIR / "images" / "test", DATA_DIR / "labels" / "test")

    measured = {
        "map50": round(float(box.map50), 4),
        "map5095": round(float(box.map), 4),
        "precision": round(mp, 4), "recall": round(mr, 4),
        "f1": round(f1, 4), "fps": round(fps, 1),
        "center_err_px": round(center_err_px, 2), "center_matches": n_matched,
        "per_class_ap50": per_class_ap,
    }
    measured["fitness"] = round(0.1 * measured["map50"] + 0.9 * measured["map5095"], 4)

    entry = registry.register(
        version=VERSION, run_name=RUN_NAME, train_mode=args.mode,
        base_model=args.base_model if args.mode == "new" else checkpoint_src,
        checkpoint_src=checkpoint_src, hyper=HYPER,
        data_counts={"train": current_fp["train_count"],
                     "valid": current_fp["valid_count"],
                     "test": current_fp["test_count"]},
        data_fingerprint=current_fp, src_pt=TRAINED_PT, metrics=measured,
    )

    print("=" * 60)
    print(f"  [{VERSION}] {RUN_NAME}  mode={args.mode}")
    print(f"  ★ Fitness    : {measured['fitness']:.4f}")
    print(f"  mAP@50       : {measured['map50']:.4f}")
    print(f"  mAP@50-95    : {measured['map5095']:.4f}")
    print(f"  Precision    : {measured['precision']:.4f}")
    print(f"  Recall       : {measured['recall']:.4f}")
    print(f"  F1           : {measured['f1']:.4f}")
    print(f"  FPS          : {measured['fps']:.1f}")
    print(f"  center error : {center_err_px:.2f} px ({n_matched} matched)")
    print("  [클래스별 AP@50]")
    for cls, ap in sorted(per_class_ap.items(), key=lambda x: -x[1]):
        flag = "  ⚠" if ap < 0.5 else ""
        print(f"    {cls:<18} {ap:.4f}{flag}")
    print("=" * 60)

    # ── 평가/메트릭 시각화 PNG 저장 ───────────────────────────────────
    try:
        viz_dir = RUNS_DIR / RUN_NAME
        save_metrics_visualization(
            out_dir=viz_dir, version=VERSION, run_name=RUN_NAME,
            metrics=measured, per_class_ap=per_class_ap,
            n_train=current_fp["train_count"],
            n_valid=current_fp["valid_count"],
            n_test=current_fp["test_count"],
        )
        print(f"  metrics PNG 저장: {viz_dir / 'metrics_summary.png'}")
        print(f"                    {viz_dir / 'per_class_ap.png'}")
        # ultralytics 자동 생성물 (test_eval 폴더) 도 같은 곳으로 복사 (리뷰 편의)
        test_eval_dir = RUNS_DIR / f"{RUN_NAME}_test_eval"
        if test_eval_dir.exists():
            for fn in ("confusion_matrix.png",
                       "confusion_matrix_normalized.png",
                       "BoxPR_curve.png", "BoxF1_curve.png",
                       "BoxP_curve.png", "BoxR_curve.png"):
                src = test_eval_dir / fn
                if src.exists():
                    shutil.copy2(src, viz_dir / f"test_{fn}")
            print(f"  ultralytics PNG 복사: test_*.png")
    except Exception as e:
        print(f"  [WARN] 메트릭 시각화 실패: {e}")

    if entry["is_best"]:
        shutil.copy2(TRAINED_PT, RUNS_DIR / "best.pt")
        print(f"\n★ NEW BEST  fitness={measured['fitness']}  ({VERSION})")
        if OD_RESOURCE.exists():
            shutil.copy2(TRAINED_PT, OD_RESOURCE / "best.pt")
            cls_map = {str(i): n for i, n in enumerate(CLASS_NAMES)}
            # production yolo.py 가 읽는 파일 (class_name.json) — 필수
            (OD_RESOURCE / "class_name.json").write_text(
                json.dumps(cls_map, indent=4, ensure_ascii=False))
            # pick_and_place_text test 가 읽는 파일 — 동기화
            (OD_RESOURCE / "class_name_tool.json").write_text(
                json.dumps(cls_map, indent=4, ensure_ascii=False))
            print(f"  OD resource 갱신 → {OD_RESOURCE / 'best.pt'}")
            print(f"  class_name.json + class_name_tool.json 갱신 ({len(CLASS_NAMES)} classes)")
        else:
            print(f"  [WARN] OD_RESOURCE 부재 — 자동 배포 스킵: {OD_RESOURCE}")


if __name__ == "__main__":
    main()
