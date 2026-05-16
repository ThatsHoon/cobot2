"""perception.py — RealSense 구독 + YOLO 객체 탐지.

비전 인지가 grasp_perception_node 로 일원화되어, 카메라 프레임 캐싱
ImgNode 와 YOLO 추론을 이 모듈이 단독 제공한다. (object_detection 폐지)
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import rclpy
import torch
from rclpy.node import Node
from sensor_msgs.msg import Image as RosImage, CameraInfo
from cv_bridge import CvBridge
from ultralytics import YOLO


# ── ImgNode: RealSense color/depth/intrinsics 캐싱 (단일 제공자) ──
class ImgNode(Node):
    """RealSense color/depth/intrinsics 프레임 캐싱 노드."""

    def __init__(self):
        super().__init__('grasp_img_node')
        self.bridge = CvBridge()
        self.color_frame = None
        self.color_frame_stamp = None
        self.depth_frame = None
        self.intrinsics = None
        self.create_subscription(
            RosImage, '/camera/camera/color/image_raw', self._color_cb, 10)
        self.create_subscription(
            RosImage, '/camera/camera/aligned_depth_to_color/image_raw',
            self._depth_cb, 10)
        self.create_subscription(
            CameraInfo, '/camera/camera/color/camera_info', self._info_cb, 10)

    def _color_cb(self, msg):
        self.color_frame = self.bridge.imgmsg_to_cv2(msg, 'bgr8')
        self.color_frame_stamp = f"{msg.header.stamp.sec}{msg.header.stamp.nanosec}"

    def _depth_cb(self, msg):
        self.depth_frame = self.bridge.imgmsg_to_cv2(msg, 'passthrough')

    def _info_cb(self, msg):
        self.intrinsics = {
            "fx": msg.k[0], "fy": msg.k[4],
            "ppx": msg.k[2], "ppy": msg.k[5],
        }

    def get_color_frame(self): return self.color_frame
    def get_color_frame_stamp(self): return self.color_frame_stamp
    def get_depth_frame(self): return self.depth_frame
    def get_camera_intrinsic(self): return self.intrinsics


# ── YOLO ─────────────────────────────────────────────────────────
@dataclass
class Detection:
    box_xyxy: Tuple[int, int, int, int]   # 원본 픽셀 좌표
    score: float
    class_id: int
    class_name: str


class YoloDetector:
    """YOLOv8 (Ultralytics) 추론 래퍼.

    target 클래스명 또는 ID 가 주어지면 best detection 1개만 반환.
    """

    def __init__(self, weights_path: Path, device: str = "0",
                 imgsz: int = 640, conf: float = 0.25, iou: float = 0.45):
        self.weights_path = Path(weights_path)
        self.device = self._resolve_device(device)
        self.imgsz = imgsz
        self.conf = conf
        self.iou = iou
        if not self.weights_path.exists():
            raise FileNotFoundError(f"YOLO weights 없음: {self.weights_path}")
        self.model = YOLO(str(self.weights_path))
        # ultralytics 모델은 names dict 를 가짐
        self.names = self.model.names

    @staticmethod
    def _resolve_device(requested: str) -> str:
        """GPU 요청인데 CUDA 가용 불가면 'cpu' 로 자동 폴백.

        ultralytics 는 device='0' 요청 시 CUDA 미가용 환경에서도 일단 model
        을 로드하고 매 추론마다 CPU 폴백 메시지를 다시 찍는다. 호출 시점에
        조용히 폴백하면 banner 중복 출력과 느린 첫 추론을 막을 수 있다.
        """
        req = str(requested).strip().lower()
        is_gpu_request = req not in ("", "cpu", "mps") and not req.startswith("cpu")
        if is_gpu_request and not torch.cuda.is_available():
            print(f"[YoloDetector] CUDA 사용 불가 — device='{requested}' → 'cpu' 폴백",
                  flush=True)
            return "cpu"
        return requested

    @staticmethod
    def auto_weights_path() -> Path:
        """gripper_approaching_sequence/resource/best.pt → 빌드 share →
        model_sequence 학습 산출물 순으로 탐색. (object_detection 폐지)"""
        PKG = "gripper_approaching_sequence"
        here = Path(__file__).resolve()
        candidates: list[Path] = []

        # 1) 정식 위치: 패키지 source 트리 resource
        src_pkg = next((p for p in here.parents if p.name == PKG), None)
        if src_pkg:
            candidates.append(src_pkg / "resource" / "best.pt")

        # 2) 빌드된 패키지 share resource
        try:
            from ament_index_python.packages import get_package_share_directory
            candidates.append(Path(get_package_share_directory(PKG)) / "resource" / "best.pt")
        except Exception:
            pass

        # 3) 보조: model_sequence 학습 산출물
        src_root = next((p for p in here.parents if p.name == "src"), None)
        if src_root is None:
            ws_root = next((p for p in here.parents
                            if (p / "src").is_dir() and (p / "install").is_dir()), None)
            src_root = (ws_root / "src") if ws_root else None
        if src_root:
            ms = src_root / "model_sequence"
            if ms.exists():
                candidates.append(ms / "runs" / "best.pt")
                candidates += sorted(
                    ms.glob("runs/v*/weights/best.pt"),
                    key=lambda p: p.stat().st_mtime, reverse=True)
                candidates += sorted(
                    ms.glob("versions/v*.pt"),
                    key=lambda p: p.stat().st_mtime, reverse=True)

        for c in candidates:
            if c.exists():
                return c
        raise FileNotFoundError("best.pt 를 찾을 수 없음")

    def resolve_class_id(self, target: str | int) -> int:
        if isinstance(target, int):
            return target
        for k, v in self.names.items():
            if str(v).lower() == target.lower():
                return int(k)
        raise KeyError(f"YOLO 모델에 '{target}' 클래스 없음. names={self.names}")

    def detect_all(self, frame_bgr: np.ndarray) -> list:
        """conf 임계값 이상의 모든 detection 을 Detection 리스트로 반환."""
        results = self.model(
            frame_bgr, imgsz=self.imgsz, conf=self.conf, iou=self.iou,
            device=self.device, verbose=False)[0]
        out = []
        if results.boxes is None or len(results.boxes) == 0:
            return out
        for b in results.boxes:
            cid = int(b.cls[0])
            score = float(b.conf[0])
            xyxy = b.xyxy[0].detach().cpu().numpy().astype(int)
            out.append(Detection(
                box_xyxy=tuple(xyxy.tolist()),
                score=score,
                class_id=cid,
                class_name=str(self.names.get(cid, str(cid))),
            ))
        return out

    def detect_best(self, frame_bgr: np.ndarray, target: str | int) -> Optional[Detection]:
        target_id = self.resolve_class_id(target)
        results = self.model(
            frame_bgr, imgsz=self.imgsz, conf=self.conf, iou=self.iou,
            device=self.device, verbose=False)[0]
        if results.boxes is None or len(results.boxes) == 0:
            return None
        best = None
        for b in results.boxes:
            cid = int(b.cls[0])
            if cid != target_id:
                continue
            score = float(b.conf[0])
            if best is None or score > best.score:
                xyxy = b.xyxy[0].detach().cpu().numpy().astype(int)
                best = Detection(
                    box_xyxy=tuple(xyxy.tolist()),
                    score=score,
                    class_id=cid,
                    class_name=str(self.names[cid]),
                )
        return best


# ── 프레임 동기 대기 (color + depth + intrinsics 동시 유효) ──────
def wait_for_frames(node: Node, img_node, timeout: float = 5.0) -> bool:
    """color/depth/intrinsics 가 모두 채워질 때까지 대기. 성공시 True.

    img_node 가 외부 executor 에 add 되어 있으면(서비스 모드) 폴링만 한다.
    add 된 노드를 spin_once 하면 이중 등록 에러가 나기 때문. --once 단독
    실행처럼 executor 가 없으면 직접 spin_once 로 펌핑한다.
    """
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        if getattr(img_node, "executor", None) is None:
            rclpy.spin_once(img_node, timeout_sec=0.1)
        else:
            time.sleep(0.05)
        if (img_node.get_color_frame() is not None
                and img_node.get_depth_frame() is not None
                and img_node.get_camera_intrinsic() is not None):
            return True
    return False


def crop_bbox(image: np.ndarray, box_xyxy, pad: int = 0) -> np.ndarray:
    """bbox 영역을 안전하게 크롭. pad 만큼 외곽 여유."""
    h, w = image.shape[:2]
    x1, y1, x2, y2 = box_xyxy
    x1 = max(0, int(x1) - pad)
    y1 = max(0, int(y1) - pad)
    x2 = min(w, int(x2) + pad)
    y2 = min(h, int(y2) + pad)
    if x2 <= x1 or y2 <= y1:
        return image
    return image[y1:y2, x1:x2].copy()
