"""grasp_geometry.py — depth 필터링 + 2D→3D 복원 + PCA 기반 grasp pose 산출.

순수 numpy. ROS 의존성 없음 → 단위 테스트 가능.

좌표계 규약:
  - RealSense color optical frame (X: right, Y: down, Z: forward).
  - 길이 단위 미터.

산출물:
  GraspPose:
    position (3,)            : 무게중심 (m, 카메라 좌표)
    rotation (3,3)           : R = [x_axis y_axis z_axis] (gripper TCP frame)
                               z_axis = -normal  (표면을 향해 접근 = approach)
                               y_axis = principal axis  (그리퍼 finger line ⊥ y)
                               x_axis = z_axis × y_axis  (gripper finger 개방 방향)
    width    float           : 그리퍼 개방 폭 (m)
    quality  float           : 신뢰도 [0,1]
    + tilt_deg / azimuth_deg / principal_yaw_deg
    + linearity / planarity   (점운 형태 진단)
    + eigvals (3,)            (PCA 고유값)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np


# ── depth 필터링 ────────────────────────────────────────────────
def filter_depth_roi(depth_mm: np.ndarray,
                     bbox_xyxy: Tuple[int, int, int, int],
                     median_band_mm: float = 50.0,
                     min_valid_ratio: float = 0.05
                     ) -> Optional[np.ndarray]:
    """ROI 의 depth 패치에서 background/이상치 제거된 mask 반환.

    Returns:
        full-image bool mask. 유효 비율이 너무 낮으면 None.
    """
    x1, y1, x2, y2 = (int(v) for v in bbox_xyxy)
    H, W = depth_mm.shape[:2]
    x1 = max(0, x1); y1 = max(0, y1)
    x2 = min(W, x2); y2 = min(H, y2)
    if x2 <= x1 or y2 <= y1:
        return None

    patch = depth_mm[y1:y2, x1:x2].astype(np.float32)
    valid = patch > 0
    if valid.sum() < 8:
        return None

    median = float(np.median(patch[valid]))
    if median <= 0:
        return None

    band_mask = valid & (np.abs(patch - median) <= median_band_mm)

    if band_mask.sum() >= 16:
        vals = patch[band_mask]
        mad = float(np.median(np.abs(vals - np.median(vals)))) + 1e-6
        z = np.abs(patch - np.median(vals)) / (1.4826 * mad)
        band_mask = band_mask & (z < 3.5)

    if band_mask.sum() < max(8, int(min_valid_ratio * (y2 - y1) * (x2 - x1))):
        return None

    full = np.zeros_like(depth_mm, dtype=bool)
    full[y1:y2, x1:x2] = band_mask
    return full


# ── 2D → 3D ─────────────────────────────────────────────────────
def deproject_mask(depth_mm: np.ndarray, mask: np.ndarray,
                   intrinsics: dict, max_points: int = 4000
                   ) -> np.ndarray:
    """mask 가 True 인 픽셀을 카메라 좌표 (m) 로 변환. (N,3)."""
    fx, fy = intrinsics["fx"], intrinsics["fy"]
    ppx, ppy = intrinsics["ppx"], intrinsics["ppy"]
    ys, xs = np.where(mask)
    if xs.size == 0:
        return np.empty((0, 3), dtype=np.float32)
    if xs.size > max_points:
        idx = np.random.choice(xs.size, max_points, replace=False)
        xs, ys = xs[idx], ys[idx]
    z = depth_mm[ys, xs].astype(np.float32) / 1000.0
    x = (xs.astype(np.float32) - ppx) * z / fx
    y = (ys.astype(np.float32) - ppy) * z / fy
    return np.stack([x, y, z], axis=1)


# ── PCA + grasp pose ────────────────────────────────────────────
@dataclass
class GraspPose:
    position: np.ndarray
    rotation: np.ndarray
    width: float
    quality: float
    centroid: np.ndarray
    axes: np.ndarray
    eigvals: np.ndarray = field(default_factory=lambda: np.zeros(3))
    tilt_deg: float = 0.0
    azimuth_deg: float = 0.0
    principal_yaw_deg: float = 0.0
    linearity: float = 0.0
    planarity: float = 0.0
    n_points_centroid: int = 0
    n_points_normal: int = 0
    grasp_mode: str = ""    # "radial" | "cylindrical" | "spherical"


def _pca(points: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    centroid = points.mean(axis=0)
    Q = points - centroid
    _, S, Vt = np.linalg.svd(Q, full_matrices=False)
    eigvals = (S ** 2) / max(1, len(points) - 1)
    axes = Vt.T   # columns = principal axes (변산도 큰 순)
    return centroid, axes, eigvals


# ── 클래스별 grasp axes 구성 ─────────────────────────────────────
# 점운 → (x_axis, y_axis, z_axis, mode_name, mode_quality_factor)
# z_axis = approach 방향 (사물 표면 향해 들어감)
# y_axis = finger line (그리퍼 두 손가락을 잇는 선)
# x_axis = finger 개방 방향 (= z × y)

def _orthonormalize(z: np.ndarray, y_hint: np.ndarray
                    ) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """z(approach) 와 y_hint 로 직교정규 (x, y, z) 구성. 퇴화면 None."""
    z = z / max(1e-9, np.linalg.norm(z))
    y_proj = y_hint - np.dot(y_hint, z) * z
    if np.linalg.norm(y_proj) < 1e-6:
        return None
    y = y_proj / np.linalg.norm(y_proj)
    x = np.cross(y, z)
    nx = np.linalg.norm(x)
    if nx < 1e-9:
        return None
    x = x / nx
    z = np.cross(x, y)
    z = z / max(1e-9, np.linalg.norm(z))
    return x, y, z


def _pick_arbitrary_perp(z: np.ndarray) -> np.ndarray:
    """z 에 수직인 임의 단위 벡터 (회전 대칭 사물용)."""
    cam_x = np.array([1., 0., 0.])
    y_proj = cam_x - np.dot(cam_x, z) * z
    if np.linalg.norm(y_proj) < 1e-6:
        cam_y = np.array([0., 1., 0.])
        y_proj = cam_y - np.dot(cam_y, z) * z
    return y_proj


def _axes_radial(axes: np.ndarray, view_dir: np.ndarray):
    """plate (방사형 disc): normal 신뢰, finger axis 회전 자유도."""
    normal = axes[:, 2]
    if np.dot(normal, view_dir) > 0:
        normal = -normal
    z_axis = -normal                                   # top-down toward disc face
    y_hint = _pick_arbitrary_perp(z_axis)              # 임의 finger axis
    o = _orthonormalize(z_axis, y_hint)
    if o is None:
        return None
    x_axis, y_axis, z_axis = o
    return x_axis, y_axis, z_axis, "radial", 0.9


def _axes_cylindrical(axes: np.ndarray, view_dir: np.ndarray):
    """banana (원통/길쭉): principal=장축, finger 가 장축 가로질러 잡음."""
    principal = axes[:, 0]
    normal = axes[:, 2]
    if np.dot(normal, view_dir) > 0:
        normal = -normal
    z_axis = -normal
    # 장축을 z_axis 평면에 투영 → finger line 방향
    y_hint = principal
    o = _orthonormalize(z_axis, y_hint)
    if o is None:
        # principal 이 z 와 평행한 퇴화 케이스 — axes[:,1] 로 폴백
        o = _orthonormalize(z_axis, axes[:, 1])
        if o is None:
            return None
    x_axis, y_axis, z_axis = o
    return x_axis, y_axis, z_axis, "cylindrical", 1.0


def _axes_spherical(axes: np.ndarray, view_dir: np.ndarray):
    """구/원형: PCA 무시, 카메라 view_dir 방향 top-down approach + 임의 finger axis.

    mode_factor=0.85 — radial(0.9)/cylindrical(1.0) 보다 약간 낮지만
    default quality_min=0.5 게이트와 충분한 마진 확보.
    """
    z_axis = view_dir / max(1e-9, np.linalg.norm(view_dir))   # 카메라 +Z = 사물 향함
    y_hint = _pick_arbitrary_perp(z_axis)
    o = _orthonormalize(z_axis, y_hint)
    if o is None:
        return None
    x_axis, y_axis, z_axis = o
    return x_axis, y_axis, z_axis, "spherical", 0.85


def _select_axes_strategy(target_class: Optional[str]):
    """클래스명 → 분석 전략 함수.
    plate → 방사형 (disc), banana → 원통형 (장축),
    그 외 (apple/orange/pear/shaker/toy_block 등) → 구체."""
    label = (target_class or "").strip().lower()
    if label == "plate":
        return _axes_radial
    if label == "banana":
        return _axes_cylindrical
    return _axes_spherical


def compute_grasp_pose(points_cam: np.ndarray,
                       normal_points: Optional[np.ndarray] = None,
                       target_class: Optional[str] = None,
                       min_points: int = 50,
                       max_width_m: float = 0.085,
                       min_width_m: float = 0.005,
                       view_dir: np.ndarray = np.array([0.0, 0.0, 1.0])
                       ) -> Optional[GraspPose]:
    """ROI 점운 → grasp pose. target_class 별 PCA 분석 전략 분기.

    Args:
        points_cam: (N,3) ROI 영역 카메라 좌표 (m). 위치(centroid) 산출에 사용.
        normal_points: (M,3) 더 넓은 영역 (예: YOLO bbox) 점운.
                       법선/주축 PCA 에 사용. None 이면 points_cam 재사용.
                       VLM ROI 가 얇은 띠일 때 PCA 퇴화를 막는 핵심 분리.
        target_class: YOLO 클래스명. 분석 전략 분기 키.
                      - 'plate'  → 방사형 (disc): normal 신뢰, finger 회전 자유도
                      - 'banana' → 원통/길쭉형: principal=장축, finger 가로질러
                      - 그 외 (apple/orange/pear/shaker/toy_block 등)
                        → 구체: PCA 무시, 카메라 +Z top-down + 임의 finger
    """
    if points_cam.shape[0] < min_points:
        return None

    # 법선 추정용 점운 결정
    if normal_points is None or normal_points.shape[0] < min_points:
        n_pts = points_cam
    else:
        n_pts = normal_points

    centroid = points_cam.mean(axis=0)
    centroid_n, axes, eigvals = _pca(n_pts)

    # 클래스별 axes 분기
    strategy = _select_axes_strategy(target_class)
    ax_result = strategy(axes, view_dir)
    if ax_result is None:
        return None
    x_axis, y_axis, z_axis, mode_name, mode_factor = ax_result
    R = np.column_stack([x_axis, y_axis, z_axis])

    # gripper width = n_pts 의 x_axis 방향 분포 (finger 개방 방향)
    width_proj = (n_pts - centroid_n) @ x_axis
    span = float(np.percentile(width_proj, 95) - np.percentile(width_proj, 5))
    width = float(np.clip(span * 1.15 + 0.01, min_width_m, max_width_m))

    # 각도 산출
    cos_tilt = float(np.clip(z_axis[2], -1.0, 1.0))
    tilt_deg = float(np.degrees(np.arccos(cos_tilt)))               # cam +Z 와 approach 의 각
    azim_deg = float(np.degrees(np.arctan2(z_axis[1], z_axis[0])))  # 이미지면 approach 방향
    pyaw_deg = float(np.degrees(np.arctan2(y_axis[1], y_axis[0])))  # 이미지면 principal axis 각

    # eigvals 분석 (진단용 + mode 별 quality 가중)
    e0, e1, e2 = float(eigvals[0]), float(eigvals[1]), float(eigvals[2])
    e0_safe = max(e0, 1e-12)
    linearity = float(np.clip((e0 - e1) / e0_safe, 0.0, 1.0))
    planarity = float(np.clip((e1 - e2) / e0_safe, 0.0, 1.0))

    # quality: 점 수 + (mode 적합성) + mode_factor
    n_factor = float(np.clip(n_pts.shape[0] / 800.0, 0.0, 1.0))
    if mode_name == "radial":
        # plate: planarity 가 높을수록 disc 가정 신뢰 ↑
        shape_score = planarity
    elif mode_name == "cylindrical":
        # banana: linearity 가 높을수록 장축 PCA 신뢰 ↑
        shape_score = linearity
    else:
        # spherical: top-down fallback 이라 사물 형태와 무관 — 기본 1.0.
        # 단, linearity 가 매우 큰 경우 (>0.7) banana 오분류 의심 → 감점.
        # cube/block 처럼 planarity 가 높은 사물은 페널티 없음.
        if linearity > 0.7:
            shape_score = float(np.clip(1.0 - (linearity - 0.7) * 5.0, 0.0, 1.0))
        else:
            shape_score = 1.0

    quality = float(np.clip(
        mode_factor * (0.4 * n_factor + 0.6 * shape_score),
        0.0, 1.0
    ))

    return GraspPose(
        position=centroid.astype(np.float64),
        rotation=R.astype(np.float64),
        width=width,
        quality=quality,
        centroid=centroid.astype(np.float64),
        axes=axes.astype(np.float64),
        eigvals=eigvals.astype(np.float64),
        tilt_deg=tilt_deg,
        azimuth_deg=azim_deg,
        principal_yaw_deg=pyaw_deg,
        linearity=linearity,
        planarity=planarity,
        n_points_centroid=int(points_cam.shape[0]),
        n_points_normal=int(n_pts.shape[0]),
        grasp_mode=mode_name,
    )


def estimate_workbench_plane(depth_mm: np.ndarray,
                             bbox_xyxy: Tuple[int, int, int, int],
                             intrinsics: dict,
                             pad_px: int = 80,
                             top_depth_percentile: float = 70.0
                             ) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """bbox 주변(pad_px 확장) raw depth 에서 워크벤치 plane 추정.

    가장 깊은 (=카메라에서 먼) 픽셀이 워크벤치라는 가정.
    median ±N 필터를 거치지 않은 RAW depth 사용 — 키 큰 사물에서도 워크벤치 보존.

    Returns:
        (centroid_m, normal) — 둘 다 카메라 좌표, m 단위. 실패 시 None.
    """
    x1, y1, x2, y2 = (int(v) for v in bbox_xyxy)
    H, W = depth_mm.shape[:2]
    # bbox 확장 (사물 주변 워크벤치를 보기 위해)
    x1 = max(0, x1 - pad_px)
    y1 = max(0, y1 - pad_px)
    x2 = min(W, x2 + pad_px)
    y2 = min(H, y2 + pad_px)
    if x2 <= x1 or y2 <= y1:
        return None

    patch = depth_mm[y1:y2, x1:x2].astype(np.float32)
    valid = patch > 0
    if valid.sum() < 50:
        return None

    # 상위 (100-percentile)% 의 깊은 픽셀 = 워크벤치 후보
    threshold = float(np.percentile(patch[valid], top_depth_percentile))
    wb_mask_local = valid & (patch >= threshold)
    if wb_mask_local.sum() < 30:
        return None

    full_mask = np.zeros_like(depth_mm, dtype=bool)
    full_mask[y1:y2, x1:x2] = wb_mask_local
    wb_pts = deproject_mask(depth_mm, full_mask, intrinsics, max_points=2000)
    if wb_pts.shape[0] < 30:
        return None

    # PCA — smallest singular vector = plane normal
    centroid = wb_pts.mean(axis=0)
    Q = wb_pts - centroid
    _, _, Vt = np.linalg.svd(Q, full_matrices=False)
    normal = Vt[-1]
    n_norm = np.linalg.norm(normal)
    if n_norm < 1e-9:
        return None
    normal = normal / n_norm
    return centroid.astype(np.float64), normal.astype(np.float64)


def perpendicular_distance(point: np.ndarray,
                           plane_centroid: np.ndarray,
                           plane_normal: np.ndarray
                           ) -> float:
    """point 에서 plane 까지의 부호 없는 수직거리 (입력 단위 그대로)."""
    return float(abs(np.dot(point - plane_centroid, plane_normal)))


def pose_pre_grasp(pose: GraspPose, standoff_m: float = 0.10) -> np.ndarray:
    """target Z축(접근 방향) 반대로 standoff 만큼 떨어진 위치 (3,)."""
    approach = pose.rotation[:, 2]
    return pose.position - approach * standoff_m


def project_to_image(p_cam: np.ndarray, intrinsics: dict
                     ) -> Optional[Tuple[int, int]]:
    """카메라 좌표 (3,) m → 이미지 픽셀. z<=0 이면 None."""
    if p_cam[2] <= 0:
        return None
    u = p_cam[0] * intrinsics["fx"] / p_cam[2] + intrinsics["ppx"]
    v = p_cam[1] * intrinsics["fy"] / p_cam[2] + intrinsics["ppy"]
    return (int(u), int(v))
