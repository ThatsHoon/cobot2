#!/usr/bin/env python3
"""integrate_fruits.py — Roboflow fruits 데이터셋을 8-class 통합셋에 합쳐 12-class 로 확장.

소스: /home/hoon/backup_extracted/Downloads/fruits  (Apple, Banana, Kiwi, Orange, Pear)
대상: /home/hoon/backup_extracted/backup/data       (shaker..glasses 8-class)

흐름:
  1. fruits 의 train/valid/test 라벨에서 kiwi(src=2) 제거
  2. kiwi 제외 후 비어버린 이미지는 풀에서 탈락
  3. 클래스 ID 리맵: src 0 Apple→8, src 4 Pear→9, src 3 Orange→10, src 1 Banana→11
  4. 기존 split(80/10/10) 유지하면서 클래스당 cap (train=160, valid=20, test=20) 적용
     - 멀티클래스 이미지는 한 번만 union, 클래스별 카운트는 각 클래스가 ≥ cap 이 될 때까지 greedy 채움
  5. 선택된 이미지는 data/images/<split>/fruits_<원본명>.jpg 로 복사,
     라벨은 remap 해서 data/labels/<split>/fruits_<원본명>.txt 로 기록
  6. 잉여 이미지는 data/backup/{apple,pear,orange,banana}/{images,labels}/ 로 복사
  7. data.yaml / train.py / prepare_dataset.py 의 CLASS_NAMES·nc 갱신은 별도 단계
"""
from __future__ import annotations
import random
import shutil
from collections import defaultdict
from pathlib import Path

SRC_ROOT = Path("/home/hoon/backup_extracted/Downloads/fruits")
DST_ROOT = Path("/home/hoon/backup_extracted/backup/data")
SEED = 42

# src class id  →  dst class id (kiwi=2 는 None=드롭)
REMAP = {0: 8, 1: 11, 3: 10, 4: 9}      # Apple→8, Banana→11, Orange→10, Pear→9
DST_NAMES = {8: "apple", 9: "pear", 10: "orange", 11: "banana"}

CAP = {"train": 160, "valid": 20, "test": 20}

# fruits 원본 디렉토리명: train/valid/test 그대로 사용
SPLITS = [("train", "train"), ("valid", "valid"), ("test", "test")]


def load_split(src_split: str):
    """fruits/<split> 의 이미지·라벨을 읽어 kiwi 제거 후 (stem, remapped_lines, classes_set) 리스트 반환."""
    img_dir = SRC_ROOT / src_split / "images"
    lbl_dir = SRC_ROOT / src_split / "labels"
    samples = []
    for img_path in sorted(img_dir.glob("*.jpg")):
        stem = img_path.stem
        lbl_path = lbl_dir / f"{stem}.txt"
        if not lbl_path.exists():
            continue
        kept_lines = []
        kept_classes = set()
        for line in lbl_path.read_text().strip().splitlines():
            parts = line.split()
            if len(parts) != 5:
                continue
            src_cls = int(parts[0])
            if src_cls not in REMAP:           # kiwi 또는 미지정 → 드롭
                continue
            dst_cls = REMAP[src_cls]
            kept_lines.append(f"{dst_cls} {parts[1]} {parts[2]} {parts[3]} {parts[4]}")
            kept_classes.add(dst_cls)
        if not kept_lines:                     # kiwi-only 이미지 탈락
            continue
        samples.append((img_path, kept_lines, kept_classes))
    return samples


def cap_select(samples, cap_per_class: int):
    """각 dst 클래스가 cap_per_class 장 이상 포함되도록 그리디 샘플링.

    한 이미지가 여러 클래스에 동시 기여 가능. 클래스 카운트가 모자란 순서로 채워서
    최종 unique 이미지 수를 최소화한다.
    """
    rng = random.Random(SEED)
    by_class: dict[int, list] = defaultdict(list)
    for s in samples:
        for c in s[2]:
            by_class[c].append(s)

    selected: dict[Path, tuple] = {}              # img_path → sample tuple
    counts: dict[int, int] = defaultdict(int)

    # 이미지가 적은(=구하기 어려운) 클래스부터 채운다 — banana 같은 minority 우선
    class_order = sorted(REMAP.values(), key=lambda c: len(by_class.get(c, [])))

    for cls in class_order:
        pool = [s for s in by_class.get(cls, []) if s[0] not in selected]
        rng.shuffle(pool)
        for s in pool:
            if counts[cls] >= cap_per_class:
                break
            selected[s[0]] = s
            for c in s[2]:
                counts[c] += 1

    return list(selected.values()), dict(counts)


def write_split(split_name: str, picks: list, dst_split_dir_name: str):
    img_out = DST_ROOT / "images" / dst_split_dir_name
    lbl_out = DST_ROOT / "labels" / dst_split_dir_name
    img_out.mkdir(parents=True, exist_ok=True)
    lbl_out.mkdir(parents=True, exist_ok=True)
    written = 0
    for img_path, lines, _ in picks:
        new_stem = f"fruits_{img_path.stem}"
        shutil.copy2(img_path, img_out / f"{new_stem}.jpg")
        (lbl_out / f"{new_stem}.txt").write_text("\n".join(lines) + "\n")
        written += 1
    return written


def stash_leftovers(split_name: str, all_samples: list, picked_paths: set):
    """선택되지 않은 이미지를 클래스별 backup/<class>/{images,labels}/<split>/ 에 보관."""
    for img_path, lines, classes in all_samples:
        if img_path in picked_paths:
            continue
        # 가장 인스턴스 많은 클래스로 라우팅 (다중 클래스 이미지는 첫 등장 기준)
        primary = next(iter(classes))
        cls_name = DST_NAMES[primary]
        bk_img = DST_ROOT / "backup" / cls_name / "images" / split_name
        bk_lbl = DST_ROOT / "backup" / cls_name / "labels" / split_name
        bk_img.mkdir(parents=True, exist_ok=True)
        bk_lbl.mkdir(parents=True, exist_ok=True)
        new_stem = f"fruits_{img_path.stem}"
        shutil.copy2(img_path, bk_img / f"{new_stem}.jpg")
        (bk_lbl / f"{new_stem}.txt").write_text("\n".join(lines) + "\n")


def main():
    print(f"SRC : {SRC_ROOT}")
    print(f"DST : {DST_ROOT}")
    print(f"SEED: {SEED}\n")

    grand_counts = defaultdict(int)
    for src_split, dst_split in SPLITS:
        samples = load_split(src_split)
        cap_n = CAP[dst_split]
        picks, counts = cap_select(samples, cap_n)
        picked_paths = {p[0] for p in picks}

        wrote = write_split(src_split, picks, dst_split)
        stash_leftovers(src_split, samples, picked_paths)

        print(f"[{src_split} → {dst_split}] cap/class={cap_n}  "
              f"source={len(samples)}  picked_unique={len(picks)}  written={wrote}")
        for cls_id in sorted(REMAP.values()):
            n = counts.get(cls_id, 0)
            grand_counts[(dst_split, cls_id)] = n
            warn = "  ⚠ under-cap" if n < cap_n else ""
            print(f"    {DST_NAMES[cls_id]:<8}(id={cls_id}): {n:>4}{warn}")

    print("\n=== 최종 fruits 클래스 분포 (이미지 기여 카운트) ===")
    for cls_id in sorted(REMAP.values()):
        row = [grand_counts.get((s, cls_id), 0) for s in ("train", "valid", "test")]
        print(f"  {DST_NAMES[cls_id]:<8}(id={cls_id}): "
              f"train={row[0]:>3}  valid={row[1]:>3}  test={row[2]:>3}")


if __name__ == "__main__":
    main()
