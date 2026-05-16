#!/usr/bin/env python3
"""prepare_dataset.py — 7-class 통합 데이터셋 빌드.

흐름:
  1. 기존 /home/rokey/backup/data/{images,labels}/* 를 backup/old_merged_<ts>/ 로 이동
  2. 2개 Roboflow 데이터셋(toy_block/plate) + 로컬 shaker
     + fruits(apple/pear/orange/banana) 사용
  3. 클래스당 200장 random sampling (seed=42), 80/10/10 split (train/valid/test)
  4. 200 초과분은 backup/<class>/{images,labels}/ 로 이동
  5. data.yaml 생성

사용:
    export ROBOFLOW_API_KEY="..."
    python3 prepare_dataset.py
    # 옵션
    python3 prepare_dataset.py --dry-run        # 다운로드/이동 없이 카운트만
    python3 prepare_dataset.py --skip-download  # cache 가 이미 있을 때

클래스: shaker, toy_block, plate, apple, pear, orange, banana
"""
from __future__ import annotations

import argparse
import os
import random
import re
import shutil
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml


# ── 설정 ────────────────────────────────────────────────────────
CLASS_NAMES = ["shaker", "toy_block", "plate",
               "apple", "pear", "orange", "banana"]
NAME2ID = {n: i for i, n in enumerate(CLASS_NAMES)}

DATA_ROOT = Path("/home/rokey/backup/data")
BACKUP_DIR = DATA_ROOT / "backup"
IMG_DIR = DATA_ROOT / "images"
LBL_DIR = DATA_ROOT / "labels"

CACHE_DIR = Path("/home/rokey/backup/model_sequence/_roboflow_cache_v2")
SHAKER_LOCAL = Path("/home/rokey/backup/model_sequence/data")

CAP_PER_CLASS = 200
TRAIN_RATIO, VALID_RATIO, TEST_RATIO = 0.80, 0.10, 0.10  # = 160 / 20 / 20
SEED = 42

# ── Roboflow 데이터셋 정의 ─────────────────────────────────────
DATASETS = [
    # shaker 는 로컬 (model_sequence/data) 사용
    {
        "tag": "shaker",
        "kind": "local",
        "src_dir": SHAKER_LOCAL,
        "class_map": {"*": "shaker"},  # 모든 외부 클래스 → shaker
    },
    {
        "tag": "toy_block",
        "kind": "roboflow",
        "workspace": "torben",
        "project": "duplo-vfvii",
        "class_map": {"*": "toy_block"},
    },
    {
        "tag": "plate",
        "kind": "roboflow",
        "workspace": "adibs-workspace",
        "project": "plate-2-cbvkb",
        "class_map": {"*": "plate"},
    },
]


# ── 유틸 ─────────────────────────────────────────────────────────
def log(msg: str):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def ensure_dirs():
    for split in ("train", "valid", "test"):
        (IMG_DIR / split).mkdir(parents=True, exist_ok=True)
        (LBL_DIR / split).mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def backup_existing_data() -> Optional[Path]:
    """현재 data/images, data/labels 안의 내용을 backup/old_merged_<ts>/ 로 이동."""
    n_files = sum(1 for _ in IMG_DIR.rglob("*.*")) + sum(1 for _ in LBL_DIR.rglob("*.*"))
    if n_files == 0:
        log("기존 데이터 없음 — 백업 스킵")
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = BACKUP_DIR / f"old_merged_{ts}"
    dst.mkdir(parents=True, exist_ok=True)
    for sub in ("images", "labels"):
        src = DATA_ROOT / sub
        if src.exists():
            tgt = dst / sub
            shutil.move(str(src), str(tgt))
    # 빈 디렉토리 재생성
    ensure_dirs()
    log(f"기존 데이터 이동 → {dst}  ({n_files} 파일)")
    return dst


# ── Roboflow 다운로드 ──────────────────────────────────────────
def download_roboflow(rf, ds: dict) -> Optional[Path]:
    """Roboflow yolov8 다운. 이미 캐시에 있으면 재사용."""
    tag = ds["tag"]
    out_dir = CACHE_DIR / tag
    # 이미 다운된 dataset 디렉토리 (data.yaml 포함) 찾기
    existing = list(out_dir.glob("*/data.yaml")) if out_dir.exists() else []
    if existing:
        loc = existing[0].parent
        log(f"  [{tag}] cache hit: {loc}")
        return loc

    log(f"  [{tag}] 다운로드 시작 ({ds['workspace']}/{ds['project']})")
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        proj = rf.workspace(ds["workspace"]).project(ds["project"])
    except Exception as e:
        log(f"  [{tag}] 프로젝트 접근 실패: {e}")
        return None

    # 최신 버전 자동 탐지
    ver_num = 1
    try:
        versions = proj.versions()
        nums = []
        for v in versions:
            m = re.search(r"/(\d+)$", str(v.id))
            if m:
                nums.append(int(m.group(1)))
        if nums:
            ver_num = max(nums)
    except Exception as e:
        log(f"  [{tag}] 버전 탐색 실패 (v1 사용): {e}")

    log(f"  [{tag}] version={ver_num} 다운 중...")
    cwd = os.getcwd()
    try:
        os.chdir(out_dir)
        ds_dl = proj.version(ver_num).download("yolov8")
        loc = Path(ds_dl.location)
        log(f"  [{tag}] OK → {loc}")
        return loc
    except Exception as e:
        log(f"  [{tag}] 다운 실패: {e}")
        return None
    finally:
        os.chdir(cwd)


# ── 데이터셋 → (이미지, 변환된 라벨) 페어 수집 ──────────────────
def gather_pairs(ds_dir: Path, class_map: Dict[str, str], target: str
                 ) -> List[Tuple[Path, str]]:
    """데이터셋 디렉토리에서 이 dataset 이 매핑되는 target 클래스의 라벨/이미지 페어.

    Returns: [(image_path, remapped_label_text), ...]
    """
    yaml_path = ds_dir / "data.yaml"
    if not yaml_path.exists():
        return []
    cfg = yaml.safe_load(yaml_path.read_text())
    ext_names = cfg.get("names", [])
    if isinstance(ext_names, dict):
        ext_names = [ext_names[k] for k in sorted(ext_names.keys())]

    target_id = NAME2ID[target]
    # ext id → our id ('*' wildcard 면 모든 ext 클래스를 target 로)
    cmap = {k.lower(): v for k, v in class_map.items()}
    ext_id_to_our = {}
    for i, name in enumerate(ext_names):
        nm = str(name).lower().strip().replace(" ", "_").replace("-", "_")
        if "*" in cmap:
            ext_id_to_our[i] = NAME2ID[cmap["*"]]
        elif nm in cmap and cmap[nm] in NAME2ID:
            ext_id_to_our[i] = NAME2ID[cmap[nm]]

    pairs = []
    for split in ("train", "valid", "test"):
        img_d = ds_dir / split / "images"
        lbl_d = ds_dir / split / "labels"
        if not img_d.exists():
            continue
        for img_p in sorted(img_d.iterdir()):
            if img_p.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                continue
            lbl_p = lbl_d / (img_p.stem + ".txt")
            if not lbl_p.exists():
                continue
            new_lines = []
            for ln in lbl_p.read_text().splitlines():
                p = ln.strip().split()
                if len(p) < 5:
                    continue
                try:
                    cid = int(p[0])
                except ValueError:
                    continue
                new_id = ext_id_to_our.get(cid)
                if new_id != target_id:
                    continue  # 이 target 이 아닌 라벨은 drop
                new_lines.append(f"{new_id} {' '.join(p[1:5])}")
            if new_lines:
                pairs.append((img_p, "\n".join(new_lines)))
    return pairs


# ── 분할 + 복사 + 잉여 백업 ────────────────────────────────────
def split_and_distribute(tag: str, pairs: List[Tuple[Path, str]],
                         dry_run: bool) -> Dict[str, int]:
    """pairs 를 cap=200 으로 sampling, 80/10/10 split, 잉여 → backup."""
    rng = random.Random(SEED + NAME2ID[tag])
    rng.shuffle(pairs)

    cap = CAP_PER_CLASS
    kept = pairs[:cap]
    surplus = pairs[cap:]

    n_kept = len(kept)
    n_train = int(round(n_kept * TRAIN_RATIO))
    n_valid = int(round(n_kept * VALID_RATIO))
    n_test = n_kept - n_train - n_valid
    if n_test < 0:
        n_test = 0
    log(f"  [{tag}] 총 {len(pairs)} → 채택 {n_kept} (train={n_train} "
        f"valid={n_valid} test={n_test})  잉여 {len(surplus)}")

    if dry_run:
        return {"total": len(pairs), "kept": n_kept,
                "train": n_train, "valid": n_valid, "test": n_test,
                "surplus": len(surplus)}

    splits = {"train": kept[:n_train],
              "valid": kept[n_train:n_train + n_valid],
              "test": kept[n_train + n_valid:]}
    for split, items in splits.items():
        for img_p, lbl_txt in items:
            new_name = f"{tag}_{img_p.name}"
            tgt_img = IMG_DIR / split / new_name
            tgt_lbl = LBL_DIR / split / (Path(new_name).stem + ".txt")
            shutil.copy2(img_p, tgt_img)
            tgt_lbl.write_text(lbl_txt + "\n")

    # 잉여는 backup/<class>/ 로
    if surplus:
        bk_dir_img = BACKUP_DIR / tag / "images"
        bk_dir_lbl = BACKUP_DIR / tag / "labels"
        bk_dir_img.mkdir(parents=True, exist_ok=True)
        bk_dir_lbl.mkdir(parents=True, exist_ok=True)
        for img_p, lbl_txt in surplus:
            new_name = f"{tag}_{img_p.name}"
            shutil.copy2(img_p, bk_dir_img / new_name)
            (bk_dir_lbl / (Path(new_name).stem + ".txt")).write_text(lbl_txt + "\n")

    return {"total": len(pairs), "kept": n_kept,
            "train": n_train, "valid": n_valid, "test": n_test,
            "surplus": len(surplus)}


# ── data.yaml ──────────────────────────────────────────────────
def write_yaml():
    cfg = {
        "path": str(DATA_ROOT),
        "train": "images/train",
        "val": "images/valid",
        "test": "images/test",
        "nc": len(CLASS_NAMES),
        "names": list(CLASS_NAMES),
    }
    p = DATA_ROOT / "data.yaml"
    p.write_text(yaml.dump(cfg, sort_keys=False, allow_unicode=True))
    log(f"data.yaml 작성: {p}")


# ── main ───────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-download", action="store_true")
    ap.add_argument("--no-backup-existing", action="store_true",
                    help="기존 data/{images,labels} 를 backup 하지 않음 (위험)")
    args = ap.parse_args()

    log("=" * 60)
    log(f"클래스 ({len(CLASS_NAMES)}): {CLASS_NAMES}")
    log(f"cap per class: {CAP_PER_CLASS}  split: "
        f"{int(TRAIN_RATIO*100)}/{int(VALID_RATIO*100)}/{int(TEST_RATIO*100)}")
    log(f"data root: {DATA_ROOT}")
    log(f"backup:    {BACKUP_DIR}")
    log("=" * 60)

    ensure_dirs()

    # 1) 기존 데이터 backup
    if not args.no_backup_existing and not args.dry_run:
        backup_existing_data()

    # 2) Roboflow 인스턴스
    rf = None
    if not args.skip_download:
        api_key = os.environ.get("ROBOFLOW_API_KEY", "").strip()
        if not api_key:
            log("ERROR: ROBOFLOW_API_KEY 미설정. 다음 중 하나 실행:")
            log('  export ROBOFLOW_API_KEY="..."')
            log("  또는 --skip-download (cache 만 사용)")
            sys.exit(1)
        from roboflow import Roboflow
        rf = Roboflow(api_key=api_key)
        log("Roboflow 인스턴스 OK")

    # 3) 각 데이터셋 다운로드 + 처리
    stats = {}
    for ds in DATASETS:
        tag = ds["tag"]
        log(f"\n>>> [{tag}] 처리 시작")

        if ds["kind"] == "local":
            ds_dir = ds["src_dir"]
            if not (ds_dir / "data.yaml").exists():
                log(f"  [{tag}] 로컬 소스 없음: {ds_dir}")
                continue
        else:  # roboflow
            if args.skip_download:
                # cache 에서 찾기
                cache_dir = CACHE_DIR / tag
                existing = list(cache_dir.glob("*/data.yaml")) if cache_dir.exists() else []
                if not existing:
                    log(f"  [{tag}] cache 없음 — skip-download 와 cache 부재 충돌")
                    continue
                ds_dir = existing[0].parent
            else:
                ds_dir = download_roboflow(rf, ds)
                if ds_dir is None:
                    continue

        pairs = gather_pairs(ds_dir, ds["class_map"], tag)
        log(f"  [{tag}] target 클래스 페어 수집: {len(pairs)}")
        if not pairs:
            log(f"  [{tag}] 매핑 가능한 라벨 없음 — 스킵")
            continue

        stats[tag] = split_and_distribute(tag, pairs, args.dry_run)

    # 4) data.yaml
    if not args.dry_run and stats:
        write_yaml()

    # 5) 요약
    log("\n" + "=" * 60)
    log("최종 분포 (kept / total / surplus)")
    log("=" * 60)
    cls_total = Counter()
    for tag, s in stats.items():
        log(f"  {tag:<11}  total={s['total']:>5}  kept={s['kept']:>4}  "
            f"(train={s['train']} valid={s['valid']} test={s['test']})  "
            f"surplus→backup={s['surplus']}")
        cls_total[tag] = s['kept']
    if not args.dry_run:
        # 실제 라벨 파일 통과 검증
        log("\n실제 디스크 라벨 분포 (재집계):")
        for split in ("train", "valid", "test"):
            c = Counter()
            for f in (LBL_DIR / split).glob("*.txt"):
                for ln in f.read_text().splitlines():
                    p = ln.split()
                    if len(p) >= 5:
                        try:
                            c[int(p[0])] += 1
                        except ValueError:
                            pass
            ds = ", ".join(f"{CLASS_NAMES[k]}={v}" for k, v in sorted(c.items()))
            log(f"  {split:5s}: {ds}")
    log("\n완료.")


if __name__ == "__main__":
    main()
