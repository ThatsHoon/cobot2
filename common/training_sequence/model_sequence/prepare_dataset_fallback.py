#!/usr/bin/env python3
"""prepare_dataset_fallback.py — plate, glasses 보조 다운로드.

원본 prepare_dataset.py 가 실패한 두 클래스에 대해 대체 URL 사용:
  - plate:   ata-ghofg/bowls-vs-plates (bowl 클래스 drop)
  - glasses: khaled-qwwx7/glasses-kwmgc (sunglasses 클래스 drop)

기존 처리된 6 클래스 데이터는 건드리지 않고, plate/glasses 만 추가.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# 동일한 헬퍼 재사용
sys.path.insert(0, str(Path(__file__).parent))
from prepare_dataset import (
    CLASS_NAMES, NAME2ID, DATA_ROOT, BACKUP_DIR, IMG_DIR, LBL_DIR,
    CACHE_DIR, CAP_PER_CLASS, TRAIN_RATIO, VALID_RATIO, TEST_RATIO,
    log, ensure_dirs, gather_pairs, split_and_distribute, write_yaml,
)

DATASETS_FALLBACK = [
    {
        "tag": "plate",
        "kind": "roboflow",
        "workspace": "ata-ghofg",
        "project": "bowls-vs-plates",
        "class_map": {
            "plate": "plate",
            "plates": "plate",
            "bowl": None,    # drop
            "bowls": None,
        },
    },
    {
        "tag": "glasses",
        "kind": "roboflow",
        "workspace": "khaled-qwwx7",
        "project": "glasses-kwmgc",
        "class_map": {
            "glasses": "glasses",
            "eyeglasses": "glasses",
            "sunglasses": None,  # drop
        },
    },
]


def gather_pairs_with_drops(ds_dir: Path, class_map: dict, target: str):
    """gather_pairs 와 동일하나 None 매핑 (drop) 지원."""
    import yaml
    yaml_path = ds_dir / "data.yaml"
    if not yaml_path.exists():
        return []
    cfg = yaml.safe_load(yaml_path.read_text())
    ext_names = cfg.get("names", [])
    if isinstance(ext_names, dict):
        ext_names = [ext_names[k] for k in sorted(ext_names.keys())]

    target_id = NAME2ID[target]
    cmap = {k.lower().strip().replace(" ", "_").replace("-", "_"): v
            for k, v in class_map.items()}

    ext_id_to_our: dict[int, int] = {}
    for i, name in enumerate(ext_names):
        nm = str(name).lower().strip().replace(" ", "_").replace("-", "_")
        # 직접 / 부분 매치
        match = cmap.get(nm)
        if match is None:
            for k, v in cmap.items():
                if k in nm or nm in k:
                    match = v
                    break
        if match is None:
            continue  # 매핑 미정의 → drop
        if match is None:
            continue  # explicit drop
        if match not in NAME2ID:
            continue
        ext_id_to_our[i] = NAME2ID[match]

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
                    continue
                new_lines.append(f"{new_id} {' '.join(p[1:5])}")
            if new_lines:
                pairs.append((img_p, "\n".join(new_lines)))
    return pairs


def download(rf, ds: dict):
    """prepare_dataset.download_roboflow 와 동일."""
    tag = ds["tag"]
    out_dir = CACHE_DIR / tag
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
        log(f"  [{tag}] 버전 탐색 실패: {e}")

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


def main():
    api_key = os.environ.get("ROBOFLOW_API_KEY", "").strip()
    if not api_key:
        print("ERROR: ROBOFLOW_API_KEY 미설정")
        sys.exit(1)
    from roboflow import Roboflow
    rf = Roboflow(api_key=api_key)

    ensure_dirs()

    for ds in DATASETS_FALLBACK:
        tag = ds["tag"]
        log(f"\n>>> [{tag}] 처리 (fallback)")
        ds_dir = download(rf, ds)
        if ds_dir is None:
            continue
        pairs = gather_pairs_with_drops(ds_dir, ds["class_map"], tag)
        log(f"  [{tag}] target 페어 수집: {len(pairs)}")
        if not pairs:
            log(f"  [{tag}] 매핑 결과 0 — 스킵")
            continue
        split_and_distribute(tag, pairs, dry_run=False)

    write_yaml()

    # 재집계
    from collections import Counter
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
        ds_str = ", ".join(f"{CLASS_NAMES[k]}={v}" for k, v in sorted(c.items()))
        log(f"  {split:5s}: {ds_str}")
    log("\n완료.")


if __name__ == "__main__":
    main()
