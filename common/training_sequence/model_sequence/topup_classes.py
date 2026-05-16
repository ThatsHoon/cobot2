#!/usr/bin/env python3
"""topup_classes.py — bottle/smartphone/glasses 활성 bbox 를 최대 600 까지 끌어올린다.

backup 풀에서 부족분을 샘플링 → 활성 split (80/10/10) 으로 이동.
이미지·라벨을 backup 에서 active 로 옮기며 라벨의 클래스 ID 도 신 10-class 로 리맵.

소스 풀:
  bottle      : data/backup/bottle/{images,labels}/*.jpg|.txt          (라벨 id=1, no remap)
  smartphone  : data/backup/smartphone/{images,labels}/*.jpg|.txt      (라벨 id=6 → 4)
  glasses     : data/backup/glasses_v2/{images,labels}/*.jpg|.txt      (라벨 id=7 → 5)
              + data/backup/old_glasses_20260507_122054/{images,labels}/{train,valid,test}/

대상: data/{images,labels}/{train,valid,test}/

전략:
  1. 활성 split 의 현재 bbox 카운트 측정
  2. needed = 600 - current_bbox
  3. 풀에서 random shuffle (seed=42), 한 장씩 누적해서 needed 달성하면 중단
  4. 선택된 이미지를 80/10/10 으로 split
  5. 이동(move) + 라벨 클래스 ID 리맵
"""
from __future__ import annotations
import random
import shutil
from collections import Counter
from pathlib import Path

DATA = Path("/home/hoon/backup_extracted/backup/data")
SEED = 42
TARGET_BBOX = 600

# new 10-class id 매핑
NEW_IDS = {"bottle": 1, "smartphone": 4, "glasses": 5}

# 각 클래스별 (label_id_old, label_id_new) — 풀 라벨에서 발견되는 ID 들
REMAP = {
    "bottle": {1: 1},
    "smartphone": {6: 4},
    "glasses": {7: 5},
}

# (img, lbl) 풀 정의: 각 클래스마다 list of (img_path, lbl_path)
def gather_pool(cls: str):
    pool = []
    if cls == "bottle":
        base = DATA / "backup" / "bottle"
        for img in sorted((base / "images").glob("*.jpg")):
            lbl = base / "labels" / f"{img.stem}.txt"
            if lbl.exists():
                pool.append((img, lbl))
    elif cls == "smartphone":
        base = DATA / "backup" / "smartphone"
        for img in sorted((base / "images").glob("*.jpg")):
            lbl = base / "labels" / f"{img.stem}.txt"
            if lbl.exists():
                pool.append((img, lbl))
    elif cls == "glasses":
        # glasses_v2 (flat)
        base = DATA / "backup" / "glasses_v2"
        for img in sorted((base / "images").glob("*.jpg")):
            lbl = base / "labels" / f"{img.stem}.txt"
            if lbl.exists():
                pool.append((img, lbl))
        # old_glasses (nested)
        base = DATA / "backup" / "old_glasses_20260507_122054"
        for split in ("train", "valid", "test"):
            for img in sorted((base / "images" / split).glob("*.jpg")):
                lbl = base / "labels" / split / f"{img.stem}.txt"
                if lbl.exists():
                    pool.append((img, lbl))
    return pool


def count_active_bbox(cls_id_new: int) -> int:
    n = 0
    for split in ("train", "valid", "test"):
        for lbl in (DATA / "labels" / split).glob("*.txt"):
            for line in lbl.read_text().splitlines():
                if line.startswith(f"{cls_id_new} "):
                    n += 1
    return n


def remap_label(lbl_path: Path, mapping: dict) -> tuple[str, int]:
    """라벨 파일 텍스트를 읽어 클래스 ID 를 리맵해서 (new_text, bbox_count) 반환."""
    lines_out = []
    cnt = 0
    for line in lbl_path.read_text().strip().splitlines():
        parts = line.split()
        if len(parts) != 5:
            continue
        try:
            old = int(parts[0])
        except ValueError:
            continue
        if old not in mapping:
            continue
        new = mapping[old]
        lines_out.append(f"{new} {parts[1]} {parts[2]} {parts[3]} {parts[4]}")
        cnt += 1
    return "\n".join(lines_out) + ("\n" if lines_out else ""), cnt


def topup_class(cls: str):
    print(f"\n=== {cls} ===")
    cls_id_new = NEW_IDS[cls]
    current = count_active_bbox(cls_id_new)
    needed = TARGET_BBOX - current
    print(f"  현재 활성 bbox: {current}")
    if needed <= 0:
        print(f"  이미 {TARGET_BBOX} 이상 — skip")
        return

    pool = gather_pool(cls)
    print(f"  풀 후보: {len(pool)} 이미지")

    # 풀 라벨의 bbox 카운트 미리 계산 (정렬용)
    rng = random.Random(SEED + hash(cls) % 1000)
    pool_with_cnt = []
    for img, lbl in pool:
        # bbox 카운트
        c = sum(1 for line in lbl.read_text().splitlines()
                if len(line.split()) == 5 and int(line.split()[0]) in REMAP[cls])
        if c > 0:
            pool_with_cnt.append((img, lbl, c))
    rng.shuffle(pool_with_cnt)

    # 누적 needed 달성될 때까지 채우기 (overshoot 최소화)
    selected = []
    accumulated = 0
    for img, lbl, c in pool_with_cnt:
        if accumulated >= needed:
            break
        # 마지막 이미지가 너무 크게 overshoot 면 (남은 1~2개라도 더 있을 때만 skip)
        if accumulated + c > needed and accumulated > 0 and (needed - accumulated) < c // 2:
            # 더 작은 후보가 남았을 가능성 있음 — 일단 skip
            continue
        selected.append((img, lbl, c))
        accumulated += c
    # 마지막 마무리: 아직 부족하면 어떻게든 채움
    if accumulated < needed:
        for img, lbl, c in pool_with_cnt:
            if (img, lbl, c) in selected:
                continue
            if accumulated >= needed:
                break
            selected.append((img, lbl, c))
            accumulated += c

    print(f"  선택: {len(selected)} 이미지  bbox={accumulated}")

    # 80/10/10 split
    rng.shuffle(selected)
    n = len(selected)
    n_train = int(n * 0.80)
    n_valid = int(n * 0.10)
    splits = {
        "train": selected[:n_train],
        "valid": selected[n_train:n_train + n_valid],
        "test": selected[n_train + n_valid:],
    }

    moved_stats = Counter()
    bbox_stats = Counter()
    for split, picks in splits.items():
        img_dst = DATA / "images" / split
        lbl_dst = DATA / "labels" / split
        img_dst.mkdir(parents=True, exist_ok=True)
        lbl_dst.mkdir(parents=True, exist_ok=True)
        for img, lbl, c in picks:
            new_text, bbox_n = remap_label(lbl, REMAP[cls])
            if bbox_n == 0:
                continue
            target_img = img_dst / img.name
            target_lbl = lbl_dst / f"{img.stem}.txt"
            if target_img.exists():
                # 동일 파일명 충돌 — 풀에서 누락
                continue
            shutil.move(str(img), str(target_img))
            target_lbl.write_text(new_text)
            try:
                lbl.unlink()                 # 원본 라벨 제거 (이미 새 텍스트로 작성)
            except FileNotFoundError:
                pass
            moved_stats[split] += 1
            bbox_stats[split] += bbox_n

    for split in ("train", "valid", "test"):
        print(f"  → {split}: 이미지 {moved_stats[split]:>4}  bbox {bbox_stats[split]:>4}")
    print(f"  TOTAL 추가: 이미지 {sum(moved_stats.values())}  bbox {sum(bbox_stats.values())}")


def clear_caches():
    n = 0
    for cache in (DATA / "labels").glob("*.cache"):
        cache.unlink()
        n += 1
    return n


def main():
    print(f"DST: {DATA}")
    print(f"TARGET bbox/class: {TARGET_BBOX}")

    for cls in ("bottle", "smartphone", "glasses"):
        topup_class(cls)

    n_cache = clear_caches()
    print(f"\n*.cache 삭제: {n_cache}")


if __name__ == "__main__":
    main()
