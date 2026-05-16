"""motion.py — Doosan m0609 동작 제어 + 좌표 변환 + OnRobot RG 그리퍼.

규약:
  - grasp_geometry.GraspPose 의 position/rotation 은 카메라 좌표계 (m).
  - 로봇은 mm 단위. T_gripper2camera.npy 의 translation 도 mm 가정 (기존 cobot_core 와 동일).
  - DSR pose: [x, y, z, rx, ry, rz] (mm, deg, ZYZ).
  - ROBOT_MODEL = "m0609" 고정 (cobot_ws 규칙).

지연 import:
  - DSR_ROBOT2 / DR_init: dryrun=False 일 때만 setup_dsr() 로 초기화
  - cobot_core.onrobot.RG: gripper_ip 가 주어졌을 때만 인스턴스화

dryrun=True 면 호출 없이 변환된 pose 만 반환 — VLM/perception 단독 테스트용.
"""
from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np

from .grasp_geometry import GraspPose, pose_pre_grasp


# ── 로봇/그리퍼 식별자 (cobot_ws 규약) ──────────────────────────
ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"


def setup_dsr(node) -> None:
    """DR_init 의 전역 id/model/node 설정. movej/movel 등 호출 전에 1회 필수.

    grasp_node.SemanticGraspNode 또는 별도 ROS Node 인스턴스를 전달.
    """
    import DR_init  # type: ignore
    DR_init.__dsr__id = ROBOT_ID
    DR_init.__dsr__model = ROBOT_MODEL
    DR_init.__dsr__node = node


def rmat_to_euler_zyz_deg(R: np.ndarray) -> np.ndarray:
    """ZYZ Euler (deg). DSR 의 get_robot_pose_matrix 와 정합."""
    # R = Rz(rx) @ Ry(ry) @ Rz(rz) 형태로 분해
    if abs(R[2, 2]) < 1.0 - 1e-7:
        ry = math.acos(np.clip(R[2, 2], -1.0, 1.0))
        rx = math.atan2(R[1, 2], R[0, 2])
        rz = math.atan2(R[2, 1], -R[2, 0])
    else:
        # gimbal: ry≈0 또는 π
        ry = 0.0 if R[2, 2] > 0 else math.pi
        rx = math.atan2(R[1, 0], R[0, 0])
        rz = 0.0
    return np.degrees([rx, ry, rz])


def cam_pose_to_base_pose(position_m: np.ndarray, R_cam_grasp: np.ndarray,
                          T_gripper2cam: np.ndarray,
                          base2gripper: np.ndarray
                          ) -> List[float]:
    """카메라 frame 의 grasp pose → base frame 6-DOF [mm,deg].

    Args:
        position_m: (3,) m, 카메라 좌표.
        R_cam_grasp: (3,3) 카메라 frame 기준 grasp rotation.
        T_gripper2cam: (4,4) — camera-frame 점을 gripper-frame 으로 옮기는 동차행렬.
                       기존 cobot_core 와 동일하게 translation 은 mm 단위로 가정.
        base2gripper: (4,4) — 현재 로봇 자세에서 gripper-frame → base-frame.
    """
    # mm 로 통일
    p_cam_mm = np.append((position_m * 1000.0), 1.0)

    base2cam = base2gripper @ T_gripper2cam
    p_base_mm = (base2cam @ p_cam_mm)[:3]

    # rotation: camera → base
    R_base_grasp = base2cam[:3, :3] @ R_cam_grasp
    rx_deg, ry_deg, rz_deg = rmat_to_euler_zyz_deg(R_base_grasp)

    return [float(p_base_mm[0]), float(p_base_mm[1]), float(p_base_mm[2]),
            float(rx_deg), float(ry_deg), float(rz_deg)]


def get_robot_pose_matrix(x_mm, y_mm, z_mm, rx_deg, ry_deg, rz_deg) -> np.ndarray:
    """DSR ZYZ Euler [mm, deg] → 4x4. cobot_core.action_manager 와 동일 규약."""
    rx, ry, rz = (math.radians(v) for v in (rx_deg, ry_deg, rz_deg))
    cz1, sz1 = math.cos(rx), math.sin(rx)
    cy,  sy  = math.cos(ry), math.sin(ry)
    cz2, sz2 = math.cos(rz), math.sin(rz)
    Rz1 = np.array([[cz1, -sz1, 0], [sz1, cz1, 0], [0, 0, 1]])
    Ry  = np.array([[cy,   0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz2 = np.array([[cz2, -sz2, 0], [sz2, cz2, 0], [0, 0, 1]])
    T = np.eye(4)
    T[:3, :3] = Rz1 @ Ry @ Rz2
    T[0, 3], T[1, 3], T[2, 3] = x_mm, y_mm, z_mm
    return T


def load_handeye_matrix():
    """gripper_approaching_sequence/resource/T_gripper2camera.npy 로드.
    미발견 시 None 반환(호출부가 dryrun 여부로 처리). 항등행렬 silent
    대체는 좌표 오변환을 숨기므로 금지(근본원인 해결)."""
    PKG = "gripper_approaching_sequence"
    try:
        from ament_index_python.packages import get_package_share_directory
        path = Path(get_package_share_directory(PKG)) / "resource" / "T_gripper2camera.npy"
        if path.exists():
            return np.load(str(path))
    except Exception:
        pass
    # 빌드 전 환경 / 단독 실행: 소스 트리에서 패키지 resource 를 직접 탐색
    here = Path(__file__).resolve()
    src_pkg = next((p for p in here.parents if p.name == PKG), None)
    src = (src_pkg / "resource" / "T_gripper2camera.npy") if src_pkg else None
    if src and src.exists():
        return np.load(str(src))
    return None


# ── 로봇 인터페이스 ─────────────────────────────────────────────
@dataclass
class GraspExecutionResult:
    success: bool
    target_base_pose: List[float]
    pre_grasp_base_pose: List[float]
    width_mm: float
    message: str = ""
    quality: float = 0.0


class DoosanGripperMotion:
    """DSR_ROBOT2 + OnRobot RG 기반 grasp 시퀀스.

    dryrun=True 면 DSR/RG 호출 없이 변환된 pose 만 반환.
    실로봇 사용 시 호출 순서:
        setup_dsr(node)               # DR_init 전역 설정
        m = DoosanGripperMotion(
            dryrun=False,
            gripper_type='rg2',       # 'rg2' or 'rg6'
            gripper_ip='192.168.1.1', # OnRobot Compute Box IP
            gripper_port=502)
        m.execute(pose)
    """

    def __init__(self, dryrun: bool = False,
                 standoff_mm: float = 100.0,
                 lift_mm: float = 150.0,
                 vel_lin: float = 200.0,
                 acc_lin: float = 50.0,
                 floor_z_mm: float = 20.0,
                 approach_offset_mm: float = 50.0,
                 gripper_type: str = "rg2",
                 gripper_ip: Optional[str] = None,
                 gripper_port: int = 502,
                 grip_force_n: float = 15.0,
                 logger=None):
        """
        grip_force_n: 그리퍼 close 시 max force (단위 N).
            - close 명령: 항상 width=0 까지 force-limited 로 진행.
              사물에 닿으면 RG2 가 자동 정지 + 그 위치를 holding force 로 유지.
            - 너무 낮으면 사물에 닿자마자 멈춰 충분히 안 잡힘 (slip).
            - 너무 높으면 부드러운 사물 (과일 등) 파손.
            - 권장: 일반 12N, 단단한 사물 18~22N, 매우 부드러운 과일 6~8N.
        """
        self.dryrun = dryrun
        self.standoff_mm = standoff_mm
        self.lift_mm = lift_mm
        self.vel_lin = vel_lin
        self.acc_lin = acc_lin
        self.floor_z_mm = floor_z_mm
        # approach 방향 진입 깊이 보정.
        # 양수=approach 방향으로 추가 진입 (centroid 안쪽으로 X mm 더), 음수=후퇴.
        self.approach_offset_mm = approach_offset_mm
        self.gripper_type = gripper_type
        self.gripper_ip = gripper_ip
        self.gripper_port = gripper_port
        self.grip_force_n = grip_force_n
        self.logger = logger or _print_logger
        self.T_gripper2cam = load_handeye_matrix()
        if self.T_gripper2cam is None:
            if self.dryrun:
                self.logger("[motion] WARN: T_gripper2camera.npy 미발견 "
                            "— dryrun 이므로 항등행렬 사용(좌표 무의미)")
                self.T_gripper2cam = np.eye(4)
            else:
                # 실로봇에서 항등행렬은 grasp 좌표를 1000배/오변환 → 충돌 위험.
                raise RuntimeError(
                    "T_gripper2camera.npy 미발견 — hand-eye 캘리브레이션 필수. "
                    "gripper_approaching_sequence/resource/ 에 배치 후 colcon build.")
        self._rg = None
        if not self.dryrun and self.gripper_ip:
            self._rg = self._open_gripper_backend()

    # ── 그리퍼 백엔드 ──────────────────────────────────────
    def _open_gripper_backend(self):
        """cobot_core.onrobot.RG 를 시도, 실패 시 None."""
        try:
            from cobot_core.onrobot import RG  # type: ignore
        except Exception as e:
            self.logger(f"[motion] cobot_core.onrobot 임포트 실패: {e} — 그리퍼 비활성화")
            return None
        try:
            rg = RG(self.gripper_type, self.gripper_ip, self.gripper_port)
            self.logger(f"[motion] OnRobot {self.gripper_type.upper()} 연결 "
                        f"({self.gripper_ip}:{self.gripper_port}) "
                        f"max_width={rg.max_width/10:.1f}mm")
            return rg
        except Exception as e:
            self.logger(f"[motion] RG 연결 실패: {e}")
            return None

    # ── 저수준 ─────────────────────────────────────────────
    def _wait_motion_idle(self, timeout_s: float = 15.0,
                          poll_s: float = 0.05,
                          start_timeout_s: float = 1.5) -> bool:
        """DSR 로봇 motion 종료까지 동기 대기.

        ★ DSR async race 회피 ★
        movej/movel 은 명령을 비동기 큐에 넣고 즉시 반환 → 컨트롤러가 명령을
        처리하기 전에 check_motion() 이 호출되면 0 (idle) 이 나와 즉시 빠져나오는
        race 발생 (특히 짧은 변위 motion 에서 노출됨).

        해결 흐름:
          (1) check_motion() != 0 (motion 시작) 까지 start_timeout_s 동안 polling
              — 그 안에 시작 신호가 안 오면 이미 idle (즉시 도달) 또는 silent reject
                로 간주하고 통과
          (2) 시작이 확인되면 mwait() 로 motion 완료 service 동기 호출
              — DSR_ROBOT2 의 공식 동기화 API. 서비스가 motion 완료까지 block.
          (3) mwait 사용 불가/실패 시 check_motion() == 0 polling 으로 fallback
        """
        if self.dryrun:
            return True
        try:
            from DSR_ROBOT2 import check_motion, mwait
        except Exception as e:
            self.logger(f"[motion] check_motion/mwait import 실패: {e}")
            return True
        # check_motion 결과 코드: 0=idle, 1=moving, 2=blending

        # (1) motion 시작 대기 (race 회피)
        t0 = time.perf_counter()
        motion_started = False
        while time.perf_counter() - t0 < start_timeout_s:
            try:
                st = check_motion()
                if st != 0:
                    motion_started = True
                    self.logger(
                        f"[motion] check_motion: motion 시작 확인 (st={st}, "
                        f"{(time.perf_counter()-t0)*1000:.0f}ms)")
                    break
            except Exception as e:
                self.logger(f"[motion] check_motion 예외: {e}")
                return False
            time.sleep(0.02)

        if not motion_started:
            # 시작 신호가 안 보임 — 두 가지 가능성:
            #   a) 이미 도달 (목표=현재 → 즉시 idle)
            #   b) silent reject (joint limit, IK 실패 등)
            # 어느 쪽이든 추가 wait 의미 없음.
            self.logger(
                f"[motion] check_motion: {start_timeout_s:.1f}s 내 motion 시작 "
                "신호 없음 — 이미 idle 가정 (또는 silent reject)")
            return True

        # (2) mwait 로 동기 대기 (공식 API)
        try:
            ret = mwait(0)
            if ret == 0:
                return True
            self.logger(f"[motion] mwait 반환 {ret} — fallback polling")
        except Exception as e:
            self.logger(f"[motion] mwait 예외: {e} — fallback polling")

        # (3) fallback: check_motion polling
        while time.perf_counter() - t0 < timeout_s:
            try:
                st = check_motion()
                if st == 0:
                    return True
            except Exception as e:
                self.logger(f"[motion] check_motion 예외: {e}")
                return False
            time.sleep(poll_s)
        self.logger(f"[motion] motion wait timeout ({timeout_s:.1f}s)")
        return False

    def _wait_gripper_idle(self, timeout_s: float = 5.0,
                           poll_s: float = 0.05) -> bool:
        """OnRobot RG motion 종료까지 polling. get_status()[0]==0 (busy 해제) 대기."""
        if self.dryrun or self._rg is None:
            return True
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < timeout_s:
            try:
                st = self._rg.get_status()
                if isinstance(st, list) and len(st) >= 1 and int(st[0]) == 0:
                    return True
            except Exception as e:
                self.logger(f"[motion] gripper status 조회 실패: {e}")
                return False
            time.sleep(poll_s)
        self.logger(f"[motion] gripper wait timeout ({timeout_s:.1f}s)")
        return False

    def _movel_abs(self, pose6: List[float]) -> bool:
        self.logger(f"[motion] movel ABS  pos={_fmt6(pose6)}")
        if self.dryrun:
            return True
        from DSR_ROBOT2 import movel, DR_MV_MOD_ABS, DR_BASE
        try:
            movel(pose6, vel=self.vel_lin, acc=self.acc_lin,
                  mod=DR_MV_MOD_ABS, ref=DR_BASE)
            # DSR movel 은 _async=0 이지만 실제로 즉시 반환되는 경우가 있음 →
            # check_motion() 폴링으로 idle 보장.
            self._wait_motion_idle()
            return True
        except Exception as e:
            self.logger(f"[motion] movel 실패: {e}")
            return False

    def _movel_preserve_orientation(self, target_xyz_mm: List[float]) -> bool:
        """target xyz 까지 movel — orientation 유지, **2-step** (z lift → xy translate).

        ★ 2-step 분리 이유 ★
        단일 movel 로 긴 Cartesian 경로 (예: 200mm+ xy + z 변화) 를 한 번에
        처리하면 IK 비연속점/wrist 한계 등으로 controller 가 silent reject 하는
        케이스가 있음. 2-step 으로 분리하면 각 segment 가 짧아 IK 안정성↑.

        흐름:
          step 1: (BEFORE_x, BEFORE_y, target_z, ori) — z 만 이동 (lift or descend)
          step 2: (target_x, target_y, target_z, ori) — xy 평행이동 (z 유지)

        z 가 단조 (step1 에서 BEFORE_z→target_z, step2 에서 target_z 유지) →
        중간에 target_z 위로 올라가지 않음.
        orientation 불변 → IK sol_space 일관 → J6 자연 보존.
        """
        if self.dryrun:
            return True
        from DSR_ROBOT2 import get_current_posj, get_current_posx, DR_BASE

        def _read_state(label):
            j = list(get_current_posj())
            px = list(get_current_posx(DR_BASE)[0])
            return j, px

        try:
            j_before, posx_before = _read_state("BEFORE")
        except Exception as e:
            self.logger(f"[motion] movel BEFORE 조회 실패: {e}")
            return False
        self.logger(
            f"[motion] movel(2-step,preserve-ori) BEFORE  "
            f"posj={[f'{v:+.2f}' for v in j_before]}  "
            f"posx={_fmt6(posx_before)}")

        target_x = float(target_xyz_mm[0])
        target_y = float(target_xyz_mm[1])
        target_z = float(target_xyz_mm[2])
        rx = float(posx_before[3])
        ry = float(posx_before[4])
        rz = float(posx_before[5])

        # ── Step 1: z 만 이동 (xy 유지) ────────────────────────
        step1_posx = [float(posx_before[0]), float(posx_before[1]),
                      target_z, rx, ry, rz]
        z_delta_step1 = abs(target_z - posx_before[2])
        if z_delta_step1 < 0.5:
            self.logger("[motion] step1 z 변화 없음 — 생략")
        else:
            self.logger(
                f"[motion] movel(2-step) #1 z lift {posx_before[2]:.1f}→{target_z:.1f}mm  "
                f"target={_fmt6(step1_posx)}")
            if not self._movel_abs(step1_posx):
                self.logger("[motion] step1 movel 호출 실패")
                return False
            try:
                _, posx_mid = _read_state("MID")
                z_err = abs(posx_mid[2] - target_z)
                if z_err > 5.0:
                    self.logger(
                        f"[motion] ⚠⚠ step1 SILENT REJECT — "
                        f"posx_mid.z={posx_mid[2]:.1f}mm, target_z={target_z:.1f}mm, "
                        f"err={z_err:.1f}mm")
                    return False
                self.logger(
                    f"[motion] movel(2-step) #1 OK  posx={_fmt6(posx_mid)}")
            except Exception as e:
                self.logger(f"[motion] step1 검증 실패: {e}")

        # ── Step 2: xy 평행이동 (z 유지) ───────────────────────
        step2_posx = [target_x, target_y, target_z, rx, ry, rz]
        xy_delta = ((target_x - posx_before[0]) ** 2
                    + (target_y - posx_before[1]) ** 2) ** 0.5
        if xy_delta < 0.5:
            self.logger("[motion] step2 xy 변화 없음 — 생략")
        else:
            self.logger(
                f"[motion] movel(2-step) #2 xy translate "
                f"({posx_before[0]:.1f},{posx_before[1]:.1f})→({target_x:.1f},{target_y:.1f})  "
                f"target={_fmt6(step2_posx)}")
            if not self._movel_abs(step2_posx):
                self.logger("[motion] step2 movel 호출 실패")
                return False

        # ── 최종 검증 ────────────────────────────────────────
        try:
            j_after, posx_after = _read_state("AFTER")
            d6 = j_after[5] - j_before[5]
            actual_delta = [abs(a - b) for a, b in zip(j_after, j_before)]
            actual_max = max(actual_delta)
            xyz_err = max(abs(posx_after[i] - step2_posx[i]) for i in range(3))
            self.logger(
                f"[motion] movel(2-step,preserve-ori) AFTER  "
                f"posj={[f'{v:+.2f}' for v in j_after]}  "
                f"posx={_fmt6(posx_after)}  "
                f"actual_delta_max={actual_max:.2f}°  J6 Δ={d6:+.2f}° "
                f"({'✓ 유지' if abs(d6) < 0.5 else '⚠ 변동'})  "
                f"xyz_err={xyz_err:.1f}mm")
            if xyz_err > 5.0:
                self.logger(
                    f"[motion] ⚠⚠ 최종 xyz 도달 실패 (err={xyz_err:.1f}mm > 5)")
                return False
        except Exception as e:
            self.logger(f"[motion] AFTER 조회 실패 (검증 불가): {e}")
        return True

    def _movej_lock_j6(self, target_xyz_mm: List[float],
                       rx_deg: float = 0.0,
                       ry_deg: float = 180.0,
                       rz_deg: float = 0.0,
                       vel_deg: float = 30.0,
                       acc_deg: float = 30.0,
                       keep_current_orientation: bool = True) -> bool:
        """target xyz 까지 movej — 6번 조인트는 현재값 그대로 유지.

        흐름:
          (1) get_current_posj() / posx 로 현재 자세 저장
          (2) keep_current_orientation=True (기본) — 인자 rx/ry/rz 무시하고
              현재 posx 의 (Rx,Ry,Rz) 를 target 자세로 사용. J5 한계 (±125°) 회피.
              False 면 인자 (rx,ry,rz) 로 IK 시도 (가능 시).
          (3) sol_space 0..7 순회, J5 등 m0609 joint limit 내인 해 중
              현재 자세에 가장 가까운 것 채택
          (4) j_target[5] = J6_lock (override)
          (5) movej(j_target, vel, acc)

        ★ keep_current_orientation=True 이유 ★
        스캔포인트 (예: J5=109°) 에서 (0,180,0) 절대 수직-하방을 요청하면
        IK 가 J5≥136° 해를 내놓아 m0609 J5 한계 ±125° 초과로 silent reject.
        intermediate 위치는 카메라 재탐지용이므로 절대 수직-하방까지 필요 없고,
        스캔포인트의 거의-수직 자세 (Ry≈-168°, 12° 기울임) 그대로 평행이동하면
        J5 변화 없이 도달 가능 + J6 자연 보존.
        2차 grasp 의 최종 수직 강제는 별도로 이미 처리됨 (execute_two_phase 참조).
        """
        if self.dryrun:
            return True
        from DSR_ROBOT2 import (
            movej, ikin, get_current_posj, get_current_posx,
            get_current_solution_space,
            DR_MV_MOD_ABS, DR_BASE,
        )
        # m0609 joint limits (deg) — J5 가 결정적 (±125°)
        # 보수적으로 잡아 silent reject 사전 차단
        M0609_LIMITS = [
            (-360.0, 360.0),  # J1
            (-125.0, 125.0),  # J2
            (-150.0, 150.0),  # J3
            (-360.0, 360.0),  # J4
            (-125.0, 125.0),  # J5  ← 이번 silent reject 의 원인 joint
            (-360.0, 360.0),  # J6
        ]

        def _in_limits(j):
            return all(lo <= v <= hi for v, (lo, hi) in zip(j, M0609_LIMITS))

        # (1) 현재 posj / posx
        try:
            j_before = list(get_current_posj())
            posx_before = list(get_current_posx(DR_BASE)[0])
            self.logger(
                f"[motion] J6 lock BEFORE  posj={[f'{v:+.2f}' for v in j_before]}  "
                f"posx={_fmt6(posx_before)}")
        except Exception as e:
            self.logger(f"[motion] get_current_posj/x 실패 (J6 lock 불가): {e}")
            return False
        j6_lock = j_before[5]

        # (2) 현재 sol_space (선호)
        try:
            preferred_sol = int(get_current_solution_space())
        except Exception as e:
            self.logger(f"[motion] get_current_solution_space 실패: {e} — sol_space=2 fallback")
            preferred_sol = 2

        # ★ orientation 결정 ★
        # keep_current_orientation=True 면 현재 posx 의 (Rx,Ry,Rz) 사용 (J5 한계 회피)
        if keep_current_orientation:
            tgt_rx = float(posx_before[3])
            tgt_ry = float(posx_before[4])
            tgt_rz = float(posx_before[5])
            self.logger(
                f"[motion] orientation 현재값 유지  "
                f"(Rx,Ry,Rz)=({tgt_rx:+.2f}, {tgt_ry:+.2f}, {tgt_rz:+.2f})  "
                f"— xyz 만 이동, J5 한계 회피")
        else:
            tgt_rx, tgt_ry, tgt_rz = float(rx_deg), float(ry_deg), float(rz_deg)
            self.logger(
                f"[motion] orientation 인자 사용  "
                f"(Rx,Ry,Rz)=({tgt_rx:+.2f}, {tgt_ry:+.2f}, {tgt_rz:+.2f})")

        target_posx = [float(target_xyz_mm[0]), float(target_xyz_mm[1]),
                       float(target_xyz_mm[2]),
                       tgt_rx, tgt_ry, tgt_rz]

        # (3) ikin — sol_space 0..7 순회, 한계 내 + 현재에 가장 가까운 해 채택
        #     선호 sol_space 를 먼저 시도해 j6_ik 가 j6_lock 에 가까운 해 우선 가능.
        sol_order = ([preferred_sol]
                     + [s for s in range(8) if s != preferred_sol])
        candidates = []   # (sol, j_ik, total_delta_to_current)
        rejected = []     # (sol, reason)
        for sol in sol_order:
            try:
                j_ik = ikin(target_posx, sol_space=sol, ref=DR_BASE)
            except Exception as e:
                rejected.append((sol, f"예외:{e}"))
                continue
            if j_ik is None or isinstance(j_ik, int):
                rejected.append((sol, f"해 없음(ret={j_ik})"))
                continue
            try:
                if len(j_ik) != 6:
                    rejected.append((sol, f"길이 이상({len(j_ik)})"))
                    continue
            except TypeError:
                rejected.append((sol, f"비정상 타입({type(j_ik).__name__})"))
                continue
            j_ik_f = [float(v) for v in j_ik]
            # J6 override 후 한계 검증 (override 후의 최종 target 으로 판단)
            j_with_lock = list(j_ik_f)
            j_with_lock[5] = j6_lock
            if not _in_limits(j_with_lock):
                # 어느 joint 가 limit 위반인지 표시
                viol = [(i, v, M0609_LIMITS[i]) for i, v in enumerate(j_with_lock)
                        if not (M0609_LIMITS[i][0] <= v <= M0609_LIMITS[i][1])]
                rejected.append(
                    (sol,
                     "joint limit 위반: "
                     + ", ".join(f"J{i+1}={v:+.2f}°(±{lo[1]:.0f})"
                                 for i, v, lo in viol)))
                continue
            dist = sum(abs(a - b) for a, b in zip(j_with_lock, j_before))
            candidates.append((sol, j_ik_f, dist))

        if not candidates:
            self.logger(
                f"[motion] ikin 모든 sol_space 실패 — target={_fmt6(target_posx)}  "
                f"reasons={rejected}")
            return False

        # 현재 자세에 가장 가까운 해 채택
        candidates.sort(key=lambda c: c[2])
        chosen_sol, j_ik_chosen, chosen_dist = candidates[0]
        self.logger(
            f"[motion] ikin OK  채택 sol_space={chosen_sol} (선호={preferred_sol})  "
            f"후보 {len(candidates)}개  거부 {len(rejected)}개  "
            f"채택해와 현재 누적Δ={chosen_dist:.2f}°")
        if rejected:
            for s, reason in rejected:
                self.logger(f"[motion]   sol_space={s} 거부: {reason}")

        # (4) J6 override
        j_target = list(j_ik_chosen)
        j6_ik = j_target[5]
        j_target[5] = j6_lock
        # 변위 계산 — silent reject 감지용
        req_delta = [abs(t - b) for t, b in zip(j_target, j_before)]
        req_max = max(req_delta)
        self.logger(
            f"[motion] J6 lock  IK J6={j6_ik:+.2f}° → 현재값 {j6_lock:+.2f}° 유지  "
            f"(sol_space={chosen_sol})  target_posj={[f'{v:+.2f}' for v in j_target]}  "
            f"요청 변위 max={req_max:.2f}°  Δ={[f'{v:.2f}' for v in req_delta]}")

        # 변위가 거의 없으면 (target ≈ current) 의도치 않은 no-op 가능
        if req_max < 0.5:
            self.logger(
                f"[motion] ⚠ 요청 변위 max={req_max:.2f}° — target 이 거의 현재 자세. "
                f"이동 생략하고 통과 (실제 motion 없음)")
            return True

        # (5) movej
        try:
            movej(j_target, vel=vel_deg, acc=acc_deg, mod=DR_MV_MOD_ABS)
            self._wait_motion_idle()
        except Exception as e:
            self.logger(f"[motion] movej 실패: {e}")
            return False

        # ★ silent reject 검증 — 실제 motion 발생 여부 확인 ★
        try:
            j_after = list(get_current_posj())
            posx_after = list(get_current_posx(DR_BASE)[0])
            actual_delta = [abs(a - b) for a, b in zip(j_after, j_before)]
            actual_max = max(actual_delta)
            d6 = j_after[5] - j6_lock
            self.logger(
                f"[motion] J6 lock AFTER  posj={[f'{v:+.2f}' for v in j_after]}  "
                f"posx={_fmt6(posx_after)}  actual_delta_max={actual_max:.2f}°  "
                f"J6 Δ={d6:+.2f}° "
                f"({'✓ 유지' if abs(d6) < 0.5 else '⚠ 변동'})")
            # silent reject: 요청은 컸는데 실제 변화는 미미
            if req_max > 5.0 and actual_max < 1.0:
                self.logger(
                    f"[motion] ⚠⚠ SILENT REJECT 감지 — 요청 변위 {req_max:.2f}° 였으나 "
                    f"실제 변화 {actual_max:.2f}°. joint limit 초과 또는 IK 비도달 의심. "
                    f"target_posj={[f'{v:+.2f}' for v in j_target]}")
                return False
        except Exception as e:
            self.logger(f"[motion] AFTER posj 조회 실패 (silent reject 검증 불가): {e}")
        return True

    # ── joint-space 이동 (movej, singularity 회피) ─────────────
    def move_to_joint(self,
                      joint_pose_deg: List[float],
                      vel_deg: float = 30.0,
                      acc_deg: float = 30.0,
                      open_gripper: bool = True,
                      label: str = "joint"
                      ) -> GraspExecutionResult:
        """movej 로 임의 joint 좌표 이동. movel 보다 안전 (singularity 회피).

        진단: 호출 전후 get_current_posj() 비교로 실제 motion 발생 여부 검증.
        DSR 가 joint limit 초과를 silent reject 하는 케이스 감지 위함.
        """
        self.logger(f"[motion] move_to_joint[{label}] target={joint_pose_deg} "
                    f"vel={vel_deg} acc={acc_deg}")
        if open_gripper and not self.dryrun and self._rg is not None:
            self._gripper("open")
        if self.dryrun:
            return GraspExecutionResult(True, [0]*6, [0]*6, 0.0, f"DRY-RUN {label}")
        try:
            self._current_base2gripper()  # wait_for_service + warm-up
        except Exception as e:
            return GraspExecutionResult(False, [0]*6, [0]*6, 0.0,
                                        f"DSR 미준비: {e}")
        from DSR_ROBOT2 import movej, get_current_posj, DR_MV_MOD_ABS
        # 호출 전 현재 joint 위치
        try:
            before = list(get_current_posj())
            self.logger(f"[motion] {label} BEFORE posj={[f'{v:.2f}' for v in before]}")
        except Exception as e:
            before = None
            self.logger(f"[motion] get_current_posj BEFORE 실패: {e}")
        try:
            movej(joint_pose_deg, vel=vel_deg, acc=acc_deg, mod=DR_MV_MOD_ABS)
            self._wait_motion_idle()
        except Exception as e:
            self.logger(f"[motion] movej[{label}] 실패: {e}")
            return GraspExecutionResult(False, [0]*6, [0]*6, 0.0,
                                        f"movej[{label}] 실패: {e}")
        # 호출 후 위치 — 실제 이동 검증
        try:
            after = list(get_current_posj())
            self.logger(f"[motion] {label} AFTER  posj={[f'{v:.2f}' for v in after]}")
            if before is not None:
                delta = [abs(a - b) for a, b in zip(after, before)]
                req_delta = [abs(t - b) for t, b in zip(joint_pose_deg, before)]
                actual_max = max(delta)
                req_max = max(req_delta)
                self.logger(f"[motion] {label} delta_max={actual_max:.2f}° "
                            f"(요청 변위 max={req_max:.2f}°)")
                # 요청 변위가 큰데 실제 변화가 미미하면 silent reject 의심
                if req_max > 5.0 and actual_max < 1.0:
                    self.logger(
                        f"[motion] ⚠ 실제 이동 거의 없음 — joint 한계 초과 또는 "
                        f"DSR silent reject 의심. target={joint_pose_deg}")
                    return GraspExecutionResult(
                        False, [0]*6, [0]*6, 0.0,
                        f"movej[{label}] silent reject (실제 이동 없음)")
        except Exception as e:
            self.logger(f"[motion] get_current_posj AFTER 실패: {e}")
        return GraspExecutionResult(True, [0]*6, [0]*6, 0.0, f"{label} OK")

    # ── 홈 위치 이동 (joint-space movej, 안전) ────────────────
    def move_home(self,
                  joint_pose_deg: Optional[List[float]] = None,
                  vel_deg: float = 30.0,
                  acc_deg: float = 30.0,
                  open_gripper: bool = True
                  ) -> GraspExecutionResult:
        """movej 로 홈 자세 이동. 기본 home: [0, 0, 90, 0, 90, 0] deg."""
        if joint_pose_deg is None:
            joint_pose_deg = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]
        self.logger(f"[motion] move_home joint={joint_pose_deg} "
                    f"vel={vel_deg} acc={acc_deg}")
        # 그리퍼 열기 (이동 중 충돌 방지)
        if open_gripper and not self.dryrun and self._rg is not None:
            self._gripper("open")
        if self.dryrun:
            return GraspExecutionResult(True, [0]*6, [0]*6, 0.0, "DRY-RUN home")
        # DSR 디스커버리 보장
        try:
            self._current_base2gripper()
        except Exception as e:
            return GraspExecutionResult(False, [0]*6, [0]*6, 0.0,
                                        f"DSR 미준비: {e}")
        from DSR_ROBOT2 import movej, DR_MV_MOD_ABS
        try:
            movej(joint_pose_deg, vel=vel_deg, acc=acc_deg, mod=DR_MV_MOD_ABS)
            self._wait_motion_idle()        # idle 보장
            return GraspExecutionResult(True, [0]*6, [0]*6, 0.0, "HOME OK")
        except Exception as e:
            self.logger(f"[motion] movej 실패: {e}")
            return GraspExecutionResult(False, [0]*6, [0]*6, 0.0,
                                        f"movej 실패: {e}")

    def _gripper(self, action: str, width_mm: Optional[float] = None) -> bool:
        """OnRobot RG 제어. action: 'open' | 'close'.

        - open:  최대 폭으로 벌림 (또는 width_mm 지정 시 그 폭 + 5mm 마진)
        - close: ★ 항상 force-limited 0-close ★
                 width=0 까지 시도, RG2 가 사물 만나면 자동 정지하고
                 그 위치를 grip_force_n 으로 holding force 로 유지.
                 (width_mm 인자는 받지만 무시 — width 추정 오차 영향 없도록 일원화)

        RG width 단위 1/10mm (정수 레지스터). force 1/10N.
        """
        self.logger(f"[motion] gripper {action}"
                    + (f" target_width={width_mm:.1f}mm (info only)" if width_mm is not None else ""))
        if self.dryrun:
            return True
        if self._rg is None:
            self.logger("[motion] gripper 비활성 (gripper_ip 미설정 또는 연결 실패) — no-op")
            return True
        try:
            force_units = int(max(0, self.grip_force_n) * 10)
            if action == "open":
                if width_mm is None:
                    self._rg.open_gripper(force_val=force_units)
                else:
                    w = int(min(self._rg.max_width, max(0, width_mm + 5.0) * 10))
                    self._rg.move_gripper(w, force_val=force_units)
            elif action == "close":
                # ★ width 추정 무시 → 항상 0 까지 force-limited close ★
                # 사물 닿으면 자동 정지 + 그 위치에서 grip_force_n 으로 holding.
                self.logger(
                    f"[motion] force-limited close: target=0  "
                    f"force={self.grip_force_n:.1f}N (max + holding)")
                self._rg.move_gripper(0, force_val=force_units)
            else:
                self.logger(f"[motion] 알 수 없는 gripper action: {action}")
                return False
            # Modbus 명령은 즉시 반환 — 그리퍼 motion 종료까지 폴링 대기.
            if not self._wait_gripper_idle():
                self.logger(f"[motion] gripper {action} timeout — 진행")
            return True
        except Exception as e:
            self.logger(f"[motion] gripper 명령 실패: {e}")
            return False

    def _current_base2gripper(self) -> np.ndarray:
        if self.dryrun:
            # dryrun: 가상의 로봇 home pose
            return get_robot_pose_matrix(400.0, 0.0, 400.0, 0.0, 90.0, 0.0)
        import DSR_ROBOT2
        from DSR_ROBOT2 import get_current_posx, DR_BASE
        # DDS 디스커버리 대기 — 새 client 가 서비스 server 를 못 찾으면
        # call_async 가 무응답 hang 됨 (특히 별도 프로세스에서 첫 호출 시).
        if not getattr(self, "_dsr_ready", False):
            cli = getattr(DSR_ROBOT2, "_ros2_get_current_posx", None)
            if cli is not None:
                self.logger("[motion] DSR 서비스 발견 대기 중 (max 10s)...")
                if not cli.wait_for_service(timeout_sec=10.0):
                    raise RuntimeError(
                        "/dsr01/aux_control/get_current_posx 서비스를 10s 내 미발견 — "
                        "bringup 또는 namespace 확인")
                self.logger("[motion] DSR 서비스 ready")
            self._dsr_ready = True
        x, y, z, rx, ry, rz = get_current_posx(DR_BASE)[0]
        return get_robot_pose_matrix(x, y, z, rx, ry, rz)

    # ── 고수준 시퀀스 ────────────────────────────────────────
    def compute_base_pose(self, pose: GraspPose):
        """camera-frame grasp pose → base-frame target/pre 6-DOF + width.

        approach_offset 보정과 floor_z 클램프까지 적용한 최종 좌표를 반환한다.
        로봇을 움직이지 않으므로 'locate' 모드(인지만)와 execute() 양쪽에서 공용.

        Returns: (target_base[6], pre_base[6], width_mm)
        """
        base2gripper = self._current_base2gripper()
        pre_pos_m = pose_pre_grasp(pose, standoff_m=self.standoff_mm / 1000.0)

        target_base = cam_pose_to_base_pose(
            pose.position, pose.rotation, self.T_gripper2cam, base2gripper)
        pre_base = cam_pose_to_base_pose(
            pre_pos_m, pose.rotation, self.T_gripper2cam, base2gripper)

        if abs(self.approach_offset_mm) > 1e-6:
            base2cam = base2gripper @ self.T_gripper2cam
            approach_base = (base2cam[:3, :3] @ pose.rotation)[:, 2]
            n = np.linalg.norm(approach_base)
            if n > 1e-9:
                approach_base = approach_base / n
                offset = approach_base * self.approach_offset_mm
                self.logger(
                    f"[motion] approach_offset={self.approach_offset_mm:+.1f}mm  "
                    f"vec={_fmt3(approach_base)}  Δ={_fmt3(offset)}")
                for i in range(3):
                    target_base[i] += float(offset[i])
                    pre_base[i] += float(offset[i])

        # 바닥 충돌 보호 — floor_z_mm 가 approach_offset 보다 우선
        target_z_before, pre_z_before = target_base[2], pre_base[2]
        target_base[2] = max(target_base[2], self.floor_z_mm)
        pre_base[2] = max(pre_base[2], self.floor_z_mm)
        if (abs(target_base[2] - target_z_before) > 0.01
                or abs(pre_base[2] - pre_z_before) > 0.01):
            self.logger(
                f"[motion] floor_z 클램프 적용 (floor={self.floor_z_mm:.1f}mm) — "
                f"target.z {target_z_before:.1f}→{target_base[2]:.1f}, "
                f"pre.z {pre_z_before:.1f}→{pre_base[2]:.1f}  "
                f"(approach_offset={self.approach_offset_mm:+.1f}mm 의 일부 무효화됨)")

        return target_base, pre_base, pose.width * 1000.0

    def execute(self, pose: GraspPose,
                on_pre_close=None,
                skip_initial_open: bool = False) -> GraspExecutionResult:
        """5-step grasp 시퀀스.

        skip_initial_open: True 면 시작 시점의 gripper open 단계 생략.
                          (이미 외부에서 그리퍼가 열려있다고 가정.)
                          execute_two_phase 의 Phase 2 진입 시 사용 — 1차 이동
                          후의 "살짝 닫히는" 모션 제거.
        on_pre_close: target 위치 도달 후 그리퍼 close 직전에 1회 호출되는 콜백.
                     "지금 카메라가 보는 장면" 캡처용 (시각적 피드백).
                     예외 발생 시 무시하고 시퀀스 계속.
        """
        target_base, pre_base, width_mm = self.compute_base_pose(pose)
        self.logger(f"[motion] grasp pose (base)  target={_fmt6(target_base)}  "
                    f"pre={_fmt6(pre_base)}  width={width_mm:.1f}mm  q={pose.quality:.2f}")

        # 시퀀스
        if not skip_initial_open:
            if not self._gripper("open", width_mm + 10.0):
                return GraspExecutionResult(False, target_base, pre_base, width_mm,
                                            "gripper open 실패")
        else:
            self.logger("[motion] skip_initial_open=True — gripper 사전 open 생략 "
                        "(이미 열려있다고 가정)")
        if not self._movel_abs(pre_base):
            return GraspExecutionResult(False, target_base, pre_base, width_mm,
                                        "pre-grasp 이동 실패")
        if not self._movel_abs(target_base):
            return GraspExecutionResult(False, target_base, pre_base, width_mm,
                                        "target 이동 실패")
        # ── 그리퍼 close 직전 시각적 피드백 캡처 (target 도달 시점 카메라 뷰) ──
        if on_pre_close is not None:
            try:
                on_pre_close()
            except Exception as e:
                self.logger(f"[motion] on_pre_close 예외 (무시): {e}")
        if not self._gripper("close", width_mm):
            return GraspExecutionResult(False, target_base, pre_base, width_mm,
                                        "gripper close 실패")
        # lift
        lift_pose = list(target_base)
        lift_pose[2] += self.lift_mm
        if not self._movel_abs(lift_pose):
            return GraspExecutionResult(False, target_base, pre_base, width_mm,
                                        "lift 실패")

        return GraspExecutionResult(True, target_base, pre_base, width_mm,
                                    "OK")

    def execute_two_phase(self, pose: GraspPose,
                          redetect_callback,
                          intermediate_z_mm: float = 450.0,
                          intermediate_y_offset_mm: float = -100.0,
                          on_pre_close=None
                          ) -> GraspExecutionResult:
        """2-phase grasp:
          1차 탐지 포인트: scan_point (호출 직전 사용자가 미리 이동 가정)
          1차 → 2차 이동: (1차 결과의 xy, z=intermediate_z_mm,
                           그리퍼 수직 하방 자세 0/180/0).
                          그리퍼 동작 없음 — 단순 movel.
          2차 탐지 포인트: 위 위치에서 redetect_callback() 호출 → 새 GraspPose
          2차 grasp: self.execute(new_pose) (open → pre → target → close → lift)

        2차 탐지 포인트의 그리퍼 자세를 항상 수직 하방으로 강제하면
        eye-in-hand 카메라가 위에서 아래로 사물을 보게 되어 depth 인식 안정화.
        """
        base2gripper = self._current_base2gripper()
        target_base = cam_pose_to_base_pose(
            pose.position, pose.rotation, self.T_gripper2cam, base2gripper)

        # ── 1차 → 2차 탐지 포인트 이동 ── (그리퍼 동작 없음)
        # 위치:
        #   x = 1차 산출 그대로
        #   y = 1차 산출 + intermediate_y_offset_mm  (default -100)
        #   z = intermediate_z_mm  (default 450, 절대값, floor 보호)
        # 자세: ZYZ (0, 180, 0) — tool +Z 가 base -Z 방향 = 그리퍼 수직 하방
        intermediate_pose = [
            float(target_base[0]),                                   # x (1차 그대로)
            float(target_base[1]) + float(intermediate_y_offset_mm), # y = 1차 + offset
            max(float(intermediate_z_mm), self.floor_z_mm),          # z = 절대 (floor 보호)
            0.0,                                                     # Rx
            180.0,                                                   # Ry  ← 수직 하방
            0.0,                                                     # Rz
        ]
        self.logger(
            f"[motion] 2차 탐지 포인트로 이동 (orientation 유지, Cartesian 직선, 동작 없음)  "
            f"y_offset={intermediate_y_offset_mm:+.1f}mm  "
            f"z={intermediate_z_mm:.1f}(절대)  "
            f"target_xyz={_fmt6(intermediate_pose[:3] + [0,0,0])[:30]}...")
        # ★ movel + orientation 유지 ★
        # - movej 는 joint-space 보간 → TCP 경로 곡선 → 중간에 z 가 target 위로 올라갈 수 있음
        # - movel + orientation 불변 → 직선 경로 + IK sol_space 일관 → J6 자연 보존
        # m0609 J5 한계 (±125°) 회피: 절대 (0,180,0) 강제 안 함, 스캔포인트의
        # 거의-수직 자세 (Ry≈-168°, ~12° 기울임) 그대로 평행이동.
        if not self._movel_preserve_orientation(
                target_xyz_mm=intermediate_pose[:3]):
            return GraspExecutionResult(False, target_base, intermediate_pose,
                                        0.0, "2차 탐지 포인트 이동 실패 (movel preserve-ori)")

        # ── motion 정착 대기 ──
        POST_MOTION_SETTLE_S = 1.5
        self.logger(
            f"[motion] motion 정착 대기 {POST_MOTION_SETTLE_S}s "
            "(check_motion idle 후 진동/카메라 안정화)")
        time.sleep(POST_MOTION_SETTLE_S)

        # ── 진단: 도달한 실제 pose 확인 ──
        # 요청한 (Rx,Ry,Rz)=(0,180,0) 와 실제 도달 pose 비교.
        # ry=180 은 ZYZ 의 gimbal lock 이라 DSR 이 다른 표현으로 바꿀 수 있음.
        if not self.dryrun:
            try:
                from DSR_ROBOT2 import get_current_posx, DR_BASE
                actual = get_current_posx(DR_BASE)[0]
                self.logger(
                    f"[motion] 1차 이동 후 실제 pose  actual={_fmt6(actual)}  "
                    f"vs requested={_fmt6(intermediate_pose)}")
                # 그리퍼 +Z 의 base-frame 방향 계산 → 수직 하방 여부 확인
                R = get_robot_pose_matrix(*actual)[:3, :3]
                tool_z_in_base = R[:, 2]      # 컬럼 3 = tool +Z 의 base-frame 표현
                tilt_from_down = math.degrees(
                    math.acos(np.clip(-tool_z_in_base[2], -1.0, 1.0)))
                self.logger(
                    f"[motion] 그리퍼 tool +Z (base frame) = "
                    f"[{tool_z_in_base[0]:+.3f}, {tool_z_in_base[1]:+.3f}, "
                    f"{tool_z_in_base[2]:+.3f}]  "
                    f"수직-하방 대비 tilt={tilt_from_down:.1f}°  "
                    f"({'✓ 수직' if tilt_from_down < 5 else '⚠ 수직 아님'})")
            except Exception as e:
                self.logger(f"[motion] 도달 pose 진단 실패: {e}")

        # ── 2차 탐지 (가까운 거리에서 fresh frame) ──
        self.logger("[motion] 2차 탐지 포인트 도달 — 재탐지 시도")
        new_pose = redetect_callback()
        if new_pose is None:
            return GraspExecutionResult(False, target_base, intermediate_pose,
                                        0.0, "2차 탐지 실패")
        self.logger(
            f"[motion] 2차 grasp 시작  "
            f"new_pos(m)={np.round(new_pose.position, 3).tolist()}  "
            f"q={new_pose.quality:.2f}")

        # ── PCA grasp pose 회전 → 수직 하방 강제 ──
        # 이유: T_gripper2camera 캘리브레이션 오차로 카메라 +Z 가 약간 기울어진 상태일 때
        # spherical/radial 모드의 z_axis (= 카메라 +Z) 가 base 프레임에서 비수직이 됨.
        # 사용자 요구: grasp 시 그리퍼는 항상 지면과 수직 → cam-frame 회전을 재계산.
        base2gripper_now = self._current_base2gripper()
        base2cam_now = base2gripper_now @ self.T_gripper2cam
        R_desired_base = get_robot_pose_matrix(0.0, 0.0, 0.0,
                                                0.0, 180.0, 0.0)[:3, :3]
        # cam-frame 회전 = (base2cam)^-1 @ R_desired_base.
        # base2cam 회전은 직교라서 inv = transpose.
        R_cam_vertical = base2cam_now[:3, :3].T @ R_desired_base
        self.logger(
            f"[motion] grasp 회전 강제 수직 — cam-frame R 재설정 "
            f"(원본 PCA 회전 무시)")
        new_pose.rotation = R_cam_vertical.astype(np.float64)

        # ── 2차 grasp (원래 로직대로 full sequence) ──
        # skip_initial_open=True: Phase 2 진입 시 그리퍼는 이미 열려 있음
        # (Scan Point / 이전 스텝). 그래야 1차 이동 후 "살짝 닫는" 모션이 안 보임.
        return self.execute(new_pose,
                             on_pre_close=on_pre_close,
                             skip_initial_open=True)


# ── 헬퍼 ────────────────────────────────────────────────────────
def _print_logger(msg: str):
    print(msg, flush=True)


def _fmt6(p) -> str:
    return "[" + ", ".join(f"{v:7.2f}" for v in p) + "]"


def _fmt3(p) -> str:
    return "[" + ", ".join(f"{v:+.3f}" for v in p) + "]"
