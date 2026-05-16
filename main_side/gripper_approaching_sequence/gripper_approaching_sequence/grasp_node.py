"""grasp_node.py — 분석 기반 자동대응 Grasp 오케스트레이터 (grasp_perception_node).

파이프라인:
  1. RealSense color/depth/intrinsics 수신 (perception.ImgNode)
  2. YOLO 로 target 클래스 bbox 탐지
  3. crop → VLM 으로 grasp ROI 추론
  4. depth 필터 → 2D→3D 복원 → PCA(구조 자동 분기) → grasp pose
  5. mode=grasp: Doosan 모션 시퀀스 (pre-grasp → target → close → lift)
     mode=locate: 모션 없이 base_pose 산출 (cobot_core BT 변칙 대응용)

서비스 인터페이스:
  /grasp_object (od_msg/GraspObject)
    - request: target_name, mode("grasp"|"locate")
    - response: success, message, base_pose[6](mm,deg ZYZ), width_mm, quality

CLI 사용:
  ros2 run gripper_approaching_sequence grasp_node            # 서비스 모드
  ros2 run gripper_approaching_sequence grasp_node --target glasses --once
  ros2 run gripper_approaching_sequence grasp_dryrun --target glasses
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.utilities import remove_ros_args
from od_msg.srv import GraspObject

from .perception import (
    ImgNode, YoloDetector, Detection,
    wait_for_frames, crop_bbox,
)
from .vlm_client import VLMClient, GraspROI, to_global_bbox
from .grasp_geometry import (
    filter_depth_roi, deproject_mask, compute_grasp_pose,
    estimate_workbench_plane, perpendicular_distance,
    GraspPose,
)
from .motion import DoosanGripperMotion, GraspExecutionResult, setup_dsr

# GraspObject.srv 의 mode 값 (서비스 계약). 클라이언트(cobot_core)도 동일 문자열 사용.
MODE_GRASP = "grasp"    # 인지 + 접근 + 파지 실행
MODE_LOCATE = "locate"  # 인지만 — base_pose 반환 (모션 없음)


SNAPSHOT_DIR = Path(__file__).resolve().parent / "_snapshots"


class SemanticGraspNode(Node):
    def __init__(self, target_class: str, dryrun: bool = False,
                 device: str = "0", weights: Optional[Path] = None,
                 vlm_model: Optional[str] = None,
                 gripper_type: str = "rg2",
                 gripper_ip: Optional[str] = None,
                 gripper_port: int = 502,
                 quality_min: float = 0.5,
                 planarity_min: float = 0.3,
                 non_planarity_max: float = 0.10,
                 approach_offset_mm: float = 50.0,
                 grip_force_n: float = 15.0,
                 save_snapshots: bool = True):
        super().__init__("grasp_perception_node")
        self.target_class = target_class
        self.dryrun = dryrun
        self.quality_min = quality_min
        self.planarity_min = planarity_min
        self.non_planarity_max = non_planarity_max
        self.save_snapshots = save_snapshots

        self.declare_parameter("target_class", target_class)

        # 1) 카메라
        self.img_node = ImgNode()

        # 2) YOLO
        wpath = weights or YoloDetector.auto_weights_path()
        self.get_logger().info(f"YOLO weights: {wpath}")
        self.yolo = YoloDetector(wpath, device=device)
        self.get_logger().info(f"YOLO classes: {self.yolo.names}")

        # 3) VLM (지연 초기화 — API 키 없을 때도 dryrun 가능)
        self._vlm: Optional[VLMClient] = None
        self._vlm_model = vlm_model

        # 4) DSR + Motion
        if not dryrun:
            try:
                setup_dsr(self)
                self.get_logger().info("DR_init 설정 완료 (id=dsr01, model=m0609)")
            except Exception as e:
                self.get_logger().warn(f"DR_init 설정 실패: {e}")
        self.motion = DoosanGripperMotion(
            dryrun=dryrun,
            gripper_type=gripper_type,
            gripper_ip=gripper_ip,
            gripper_port=gripper_port,
            approach_offset_mm=approach_offset_mm,
            grip_force_n=grip_force_n,
            logger=lambda m: self.get_logger().info(m))

        # 5) 서비스 — 통합 인지/파지 인터페이스.
        # ReentrantCallbackGroup: 장시간(VLM/모션) 콜백이 다른 콜백을 막지 않게.
        # _busy: DSR 모션은 비재진입 → 동시 요청 거부.
        self._busy = threading.Lock()
        self.create_service(GraspObject, "/grasp_object", self._on_grasp_object,
                            callback_group=ReentrantCallbackGroup())
        self.get_logger().info(
            f"[ready] target={target_class}  dryrun={dryrun}  "
            f"service=/grasp_object (mode: grasp|locate)")

    # ── lazy VLM ──────────────────────────────────────────
    def _get_vlm(self) -> VLMClient:
        if self._vlm is None:
            self._vlm = VLMClient(model=self._vlm_model or "gpt-4o")
        return self._vlm

    # ── 한 사이클 ─────────────────────────────────────────
    def run_once(self, target: Optional[str] = None) -> GraspExecutionResult:
        """mode=grasp: 인지 → 접근 → 파지 전체 수행."""
        return self._run(target, do_motion=True)

    def run_locate(self, target: Optional[str] = None) -> GraspExecutionResult:
        """mode=locate: 인지만. 로봇 모션 없이 base_pose 산출 (BT 변칙 대응용)."""
        return self._run(target, do_motion=False)

    def _run(self, target: Optional[str], do_motion: bool) -> GraspExecutionResult:
        target = target or self.get_parameter("target_class").value or self.target_class
        mode = MODE_GRASP if do_motion else MODE_LOCATE
        self.get_logger().info(f"=== {mode} cycle start  target={target} ===")

        if not wait_for_frames(self, self.img_node, timeout=5.0):
            return _fail("RealSense 프레임 미수신 (5s timeout)")

        color = self.img_node.get_color_frame()
        depth = self.img_node.get_depth_frame()
        intr = self.img_node.get_camera_intrinsic()
        self.get_logger().info(
            f"frame: color={color.shape}  depth={depth.shape}  intr={intr}")

        # 1) YOLO
        det: Optional[Detection] = self.yolo.detect_best(color, target)
        if det is None:
            return _fail(f"'{target}' YOLO 탐지 실패")
        self.get_logger().info(
            f"YOLO det: bbox={det.box_xyxy} score={det.score:.2f}")

        # 2) ROI 결정 — plate 만 VLM, 그 외는 YOLO bbox 그대로 사용
        label = det.class_name.strip().lower()
        if label == "plate":
            # plate 는 outer rim 위치가 grasp 에 중요 → VLM 으로 rim ROI 추출
            VLM_CROP_PAD = 60
            crop = crop_bbox(color, det.box_xyxy, pad=VLM_CROP_PAD)
            try:
                roi: GraspROI = self._get_vlm().query_grasp_roi(crop, det.class_name)
            except Exception as e:
                return _fail(f"VLM 호출 실패: {e}")
            cx1 = max(0, int(det.box_xyxy[0]) - VLM_CROP_PAD)
            cy1 = max(0, int(det.box_xyxy[1]) - VLM_CROP_PAD)
            grasp_roi = to_global_bbox(roi.bbox, (cx1, cy1))
            self.get_logger().info(
                f"[plate] VLM ROI (crop)={roi.bbox}  global={grasp_roi}  "
                f"reason={roi.reason!r}")
        else:
            # 그 외 클래스: YOLO bbox 그대로 ROI 로 사용 (API 호출 없음)
            grasp_roi = tuple(int(v) for v in det.box_xyxy)
            self.get_logger().info(
                f"[{det.class_name}] YOLO bbox 직접 사용 — ROI={grasp_roi} (no VLM)")

        # 3) depth 필터 + 3D
        # 3a) 법선/PCA 용 BBox 영역 점운 (plate 일 때만 별도 — rim ROI 가 얇아 PCA 퇴화 가능)
        if label == "plate":
            bbox_mask = filter_depth_roi(depth, det.box_xyxy, median_band_mm=80.0)
            if bbox_mask is not None:
                bbox_pts = deproject_mask(depth, bbox_mask, intr, max_points=4000)
                self.get_logger().info(f"bbox cloud (for normal): N={bbox_pts.shape[0]}")
            else:
                bbox_pts = None
                self.get_logger().warn("bbox depth 필터 실패 — ROI 점운으로 법선 추정")
        else:
            bbox_pts = None    # 비-plate: ROI = bbox 라 별도 cloud 불필요

        # 3b) ROI 점운 (centroid 산출 + 비-plate 의 PCA)
        mask = filter_depth_roi(depth, grasp_roi, median_band_mm=50.0)
        if mask is None:
            return _fail("depth ROI 필터 실패 (유효 픽셀 부족)")
        pts = deproject_mask(depth, mask, intr, max_points=4000)
        self.get_logger().info(f"roi cloud: N={pts.shape[0]}")

        # 4) PCA → grasp pose (target_class 기반 분기: plate=radial, banana=cylindrical, 그 외=spherical)
        pose = compute_grasp_pose(pts, normal_points=bbox_pts,
                                  target_class=det.class_name)
        if pose is None:
            return _fail("grasp pose 계산 실패 (포인트 부족 또는 퇴화)")
        self.get_logger().info(
            f"pose: mode={pose.grasp_mode}  pos(m)={np.round(pose.position,3).tolist()}  "
            f"width={pose.width*1000:.1f}mm  q={pose.quality:.2f}")
        self.get_logger().info(
            f"  eigvals=[{pose.eigvals[0]:.4f},{pose.eigvals[1]:.4f},"
            f"{pose.eigvals[2]:.4f}]  "
            f"linearity={pose.linearity:.2f}  planarity={pose.planarity:.2f}")
        self.get_logger().info(
            f"  tilt={pose.tilt_deg:.1f}°  azimuth={pose.azimuth_deg:+.1f}°  "
            f"p_yaw={pose.principal_yaw_deg:+.1f}°")

        # 4-bis) 워크벤치 plane 추정 → 동적 approach_offset 산출
        # ROI 표면(centroid) → 바닥(workbench plane) 까지 수직거리 측정,
        # 그 절반만큼 approach 방향으로 진입 (최대 50mm)
        APPROACH_OFFSET_CAP_MM = 80.0
        wb = estimate_workbench_plane(depth, det.box_xyxy, intr, pad_px=80)
        if wb is not None:
            wb_centroid_m, wb_normal = wb
            obj_height_m = perpendicular_distance(
                pose.position, wb_centroid_m, wb_normal)
            obj_height_mm = obj_height_m * 1000.0
            # h/2 + 20mm 추가 진입 (사용자 보정), cap 으로 클램프
            dyn_offset_mm = min(obj_height_mm / 2.0 + 20.0, APPROACH_OFFSET_CAP_MM)
            dyn_offset_mm = max(0.0, dyn_offset_mm)  # 음수 방지
            self.motion.approach_offset_mm = dyn_offset_mm
            self.get_logger().info(
                f"  workbench plane OK — obj_height={obj_height_mm:.1f}mm "
                f"→ approach_offset={dyn_offset_mm:.1f}mm "
                f"(cap={APPROACH_OFFSET_CAP_MM:.0f}mm)")
        else:
            self.get_logger().warn(
                f"  workbench plane 추정 실패 — "
                f"approach_offset 기본값 유지 ({self.motion.approach_offset_mm:.1f}mm)")

        # 진단 스냅샷 (게이트 거부 케이스도 기록되도록 게이트 직전에 저장)
        if self.save_snapshots:
            self._save_snapshot(color, det, grasp_roi, pose)

        # 4-A) 품질 게이트 — 신뢰 낮은 pose 로 로봇 동작하지 않음
        if pose.quality < self.quality_min:
            return _fail(
                f"quality {pose.quality:.2f} < {self.quality_min:.2f} "
                f"— 재촬영/재시도 권장")
        if pose.planarity < self.planarity_min:
            return _fail(
                f"planarity {pose.planarity:.2f} < {self.planarity_min:.2f} "
                f"— 평면 추정 부적절")
        # 곡률 게이트 — sqrt(λ3)/sqrt(λ1) 가 큰 ROI = 굴곡 표면 (bowl/dish)
        l1 = float(max(1e-12, pose.eigvals[0]))
        l3 = float(max(0.0, pose.eigvals[2]))
        non_planarity = (l3 / l1) ** 0.5
        if non_planarity > self.non_planarity_max:
            return _fail(
                f"non-planarity {non_planarity:.0%} > "
                f"{self.non_planarity_max:.0%} — 굴곡 표면 (bowl/dish 의심)")

        # 5) grasp = 모션 실행 / locate = base_pose 산출만
        if do_motion:
            result = self.motion.execute(pose)
        else:
            tb, pb, w = self.motion.compute_base_pose(pose)
            result = GraspExecutionResult(True, tb, pb, w, "LOCATE OK")
        result.quality = float(pose.quality)
        self.get_logger().info(f"=== {mode} done  success={result.success}  "
                               f"msg={result.message} ===")
        return result

    # ── 서비스 핸들러 (GraspObject) ──────────────────────
    def _on_grasp_object(self, req: GraspObject.Request,
                         resp: GraspObject.Response) -> GraspObject.Response:
        mode = (req.mode or MODE_GRASP).strip().lower()
        tgt = req.target_name or None
        # DSR 모션·인지 파이프라인은 비재진입 → 동시 요청 즉시 거부
        if not self._busy.acquire(blocking=False):
            resp.success = False
            resp.message = "busy: 다른 grasp 요청 처리 중"
            resp.base_pose = [0.0] * 6
            resp.width_mm = 0.0
            resp.quality = 0.0
            return resp
        try:
            r = self.run_locate(tgt) if mode == MODE_LOCATE else self.run_once(tgt)
            resp.success = bool(r.success)
            resp.message = f"[{mode}] {r.message} | base={_fmt6(r.target_base_pose)}"
            resp.base_pose = [float(v) for v in r.target_base_pose]
            resp.width_mm = float(r.width_mm)
            resp.quality = float(r.quality) if r.success else 0.0
        except Exception as e:
            traceback.print_exc()
            resp.success = False
            resp.message = f"exception: {e}"
            resp.base_pose = [0.0] * 6
            resp.width_mm = 0.0
            resp.quality = 0.0
        finally:
            self._busy.release()
        return resp

    def _save_snapshot(self, color, det: Detection,
                       grasp_roi, pose: GraspPose):
        try:
            SNAPSHOT_DIR.mkdir(exist_ok=True)
            img = color.copy()
            x1, y1, x2, y2 = det.box_xyxy
            cv2.rectangle(img, (x1, y1), (x2, y2), (102, 230, 76), 2)
            cv2.putText(img, f"{det.class_name} {det.score:.2f}",
                        (x1, max(0, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
            gx1, gy1, gx2, gy2 = grasp_roi
            # plate: VLM rim ROI (YOLO bbox 와 다름) — 빨강 별도 표시
            # 그 외: ROI == YOLO bbox — 빨강 박스가 초록과 겹쳐 그려짐 (시각적 OK)
            cv2.rectangle(img, (gx1, gy1), (gx2, gy2), (0, 0, 255), 2)
            cv2.putText(img, "grasp_roi", (gx1, max(0, gy1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 1)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = SNAPSHOT_DIR / f"grasp_{ts}.jpg"
            cv2.imwrite(str(path), img)
            self.get_logger().info(f"snapshot: {path}")
        except Exception as e:
            self.get_logger().warn(f"snapshot 실패: {e}")


def _fail(msg: str) -> GraspExecutionResult:
    return GraspExecutionResult(False, [0.0]*6, [0.0]*6, 0.0, msg)


def _fmt6(p):
    return "[" + ", ".join(f"{v:7.2f}" for v in p) + "]"


# ── 엔트리포인트 ─────────────────────────────────────────────────
def _parse_args(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="glasses",
                    help="YOLO 클래스명")
    ap.add_argument("--device", default="0", help="0|cpu")
    ap.add_argument("--weights", type=Path, default=None)
    ap.add_argument("--vlm-model", default=None)
    ap.add_argument("--once", action="store_true",
                    help="서비스 대기 없이 1사이클만 실행 후 종료")
    ap.add_argument("--dryrun", action="store_true",
                    help="DSR_ROBOT2 호출 없음 — 변환 결과만 출력")
    ap.add_argument("--gripper-type", default="rg2", choices=["rg2", "rg6"],
                    help="OnRobot 그리퍼 종류")
    ap.add_argument("--gripper-ip", default=None,
                    help="OnRobot Compute Box IP (없으면 그리퍼 비활성)")
    ap.add_argument("--gripper-port", type=int, default=502,
                    help="OnRobot Modbus TCP 포트 (기본 502)")
    ap.add_argument("--no-snapshots", action="store_true")
    ap.add_argument("--quality-min", type=float, default=0.5,
                    help="GraspPose.quality 최소 임계 (기본 0.5)")
    ap.add_argument("--planarity-min", type=float, default=0.3,
                    help="PCA planarity 최소 임계 (기본 0.3)")
    ap.add_argument("--non-planarity-max", type=float, default=0.10,
                    help="sqrt(λ3)/sqrt(λ1) 상한 (기본 0.10). "
                         "굴곡 표면 (bowl/dish) 자동 거부용")
    ap.add_argument("--approach-offset-mm", type=float, default=50.0,
                    help="approach 방향 진입 깊이 보정 (기본 +50mm). "
                         "양수=centroid 안쪽으로 더 진입, 음수=후퇴, 0=비활성")
    ap.add_argument("--grip-force-n", type=float, default=15.0,
                    help="그리퍼 close 시 max + holding force (N). "
                         "기본 15N. 부드러운 과일 8~10N, 단단한 사물 20~25N. "
                         "width 추정 오차 무관하게 0 까지 force-limited close.")
    # parse_known_args: ros2 launch 가 붙이는 --ros-args 등 미지 인자를 무시
    # (parse_args 면 SystemExit → 런치 즉사).
    args, _ = ap.parse_known_args(argv)
    return args


def main(argv=None):
    raw = list(argv) if argv is not None else sys.argv
    rclpy.init(args=raw)
    # ROS 인자(--ros-args …) 제거 후 CLI 인자만 argparse 로 파싱
    cli_argv = remove_ros_args(args=raw)[1:]
    args = _parse_args(cli_argv)
    node = SemanticGraspNode(
        target_class=args.target,
        dryrun=args.dryrun,
        device=args.device,
        weights=args.weights,
        vlm_model=args.vlm_model,
        gripper_type=args.gripper_type,
        gripper_ip=args.gripper_ip,
        gripper_port=args.gripper_port,
        quality_min=args.quality_min,
        planarity_min=args.planarity_min,
        non_planarity_max=args.non_planarity_max,
        approach_offset_mm=args.approach_offset_mm,
        grip_force_n=args.grip_force_n,
        save_snapshots=not args.no_snapshots,
    )
    try:
        if args.once:
            node.run_once()
        else:
            # 단일스레드 spin 이면 장시간 grasp 콜백이 노드 전체를 막는다.
            # MultiThreadedExecutor + img_node 동시 spin → 프레임 상시 갱신,
            # 서비스 콜백(ReentrantCallbackGroup)이 다른 콜백을 굶기지 않음.
            executor = MultiThreadedExecutor(num_threads=4)
            executor.add_node(node)
            executor.add_node(node.img_node)
            try:
                executor.spin()
            finally:
                executor.shutdown()
    except KeyboardInterrupt:
        pass
    finally:
        node.img_node.destroy_node()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def dryrun_main(argv=None):
    """엔트리포인트 단축형 — 항상 dryrun=True."""
    forced = list(argv or sys.argv[1:])
    if "--dryrun" not in forced:
        forced.append("--dryrun")
    if "--once" not in forced:
        forced.append("--once")
    main(forced)


if __name__ == "__main__":
    main()
