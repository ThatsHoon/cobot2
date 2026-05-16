#!/usr/bin/env python3
"""integrate_real_data.py — /home/hoon/Downloads/real_data 의 7-class 데이터를
현재 활성 10-class 데이터셋(/home/hoon/backup_extracted/backup/data) 에 합친다.

소스: 378 train 이미지 (multi-class, valid/test 없음)
  src class:  0=apple, 1=banana, 2=orange, 3=pear, 4=plate, 5=shaker, 6=toy_block

대상 활성 10-class:
  0=shaker, 1=bottle, 2=toy_block, 3=plate, 4=smartphone, 5=glasses,
  6=apple, 7=pear, 8=orange, 9=banana

흐름:
  1. 378장 random shuffle (seed=42) → 80/10/10 = 302/38/38 split
  2. 라벨 클래스 ID 리맵 (src→dst)
  3. images/<split>/real_<원본명>.jpg + labels/<split>/real_<원본명>.txt 로 복사
  4. *.cache 삭제
"""
from __future__ import annotations
import random
import shutil
from collections import Counter, defaultdict
from pathlib import Path

SRC = Path("/home/hoon/Downloads/real_data/train")
DST = Path("/home/hoon/backup_extracted/backup/data")
SEED = 42

# src class id  →  dst class id
REMAP = {
    0: 6,   # apple   → 6
    1: 9,   # banana  → 9
    2: 8,   # orange  → 8
    3: 7,   # pear    → 7
    4: 3,   # plate   → 3
    5: 0,   # shaker  → 0
    6: 2,   # toy_block → 2
}
DST_NAMES = {0: "shaker", 1: "bottle", 2: "toy_block", 3: "plate",
             4: "smartphone", 5: "glasses",
             6: "apple", 7: "pear", 8: "orange", 9: "banana"}

# 80/10/10
RATIOS = {"train": 0.80, "valid": 0.10, "test": 0.10}


def poly_to_bbox(coords):
    """polygon (x1,y1,x2,y2,...) 정규화 좌표 → bbox (cx, cy, w, h) 정규화."""
    xs = coords[0::2]
    ys = coords[1::2]
    x_min, x_max = max(0.0, min(xs)), min(1.0, max(xs))
    y_min, y_max = max(0.0, min(ys)), min(1.0, max(ys))
    cx = (x_min + x_max) / 2.0
    cy = (y_min + y_max) / 2.0
    w = max(0.0, x_max - x_min)
    h = max(0.0, y_max - y_min)
    return cx, cy, w, h


def collect_samples():
    """모든 (img_path, remapped_lines) 수집.

    real_data 라벨은 YOLO segmentation polygon 형식 (가변 길이) — bbox 로 변환.
    """
    img_dir = SRC / "images"
    lbl_dir = SRC / "labels"
    samples = []
    fmt_stats = {"bbox": 0, "poly": 0, "skip": 0}
    for img in sorted(img_dir.glob("*.jpg")):
        lbl = lbl_dir / f"{img.stem}.txt"
        if not lbl.exists():
            continue
        new_lines = []
        for line in lbl.read_text().strip().splitlines():
            parts = line.split()
            if len(parts) < 5:
                fmt_stats["skip"] += 1
                continue
            try:
                src_cls = int(parts[0])
            except ValueError:
                fmt_stats["skip"] += 1
                continue
            if src_cls not in REMAP:
                fmt_stats["skip"] += 1
                continue
            dst_cls = REMAP[src_cls]
            if len(parts) == 5:
                fmt_stats["bbox"] += 1
                cx, cy, w, h = (float(parts[1]), float(parts[2]),
                                 float(parts[3]), float(parts[4]))
            else:
                # polygon: 짝수 개 좌표여야 함
                coords = list(map(float, parts[1:]))
                if len(coords) < 6 or len(coords) % 2 != 0:
                    fmt_stats["skip"] += 1
                    continue
                fmt_stats["poly"] += 1
                cx, cy, w, h = poly_to_bbox(coords)
            if w <= 0 or h <= 0:
                fmt_stats["skip"] += 1
                continue
            new_lines.append(f"{dst_cls} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
        if new_lines:
            samples.append((img, new_lines))
    print(f"[parse] bbox={fmt_stats['bbox']}  poly→bbox={fmt_stats['poly']}  skipped={fmt_stats['skip']}")
    return samples


def split_samples(samples):
    rng = random.Random(SEED)
    shuffled = samples[:]
    rng.shuffle(shuffled)
    n = len(shuffled)
    n_train = int(n * RATIOS["train"])
    n_valid = int(n * RATIOS["valid"])
    # 나머지는 test 로
    train = shuffled[:n_train]
    valid = shuffled[n_train:n_train + n_valid]
    test = shuffled[n_train + n_valid:]
    return {"train": train, "valid": valid, "test": test}


def write_split(split: str, picks):
    img_out = DST / "images" / split
    lbl_out = DST / "labels" / split
    img_out.mkdir(parents=True, exist_ok=True)
    lbl_out.mkdir(parents=True, exist_ok=True)
    counter = Counter()
    img_count = 0
    for img_path, lines in picks:
        new_stem = f"real_{img_path.stem}"
        shutil.copy2(img_path, img_out / f"{new_stem}.jpg")
        (lbl_out / f"{new_stem}.txt").write_text("\n".join(lines) + "\n")
        img_count += 1
        for line in lines:
            cid = int(line.split()[0])
            counter[cid] += 1
    return img_count, counter


def clear_caches():
    n = 0
    for cache in (DST / "labels").glob("*.cache"):
        cache.unlink()
        n += 1
    return n


def main():
    print(f"SRC : {SRC}")
    print(f"DST : {DST}")
    print(f"SEED: {SEED}\n")

    samples = collect_samples()
    print(f"수집된 샘플: {len(samples)} 이미지\n")

    splits = split_samples(samples)
    grand = {}
    for split in ("train", "valid", "test"):
        n_img, cnt = write_split(split, splits[split])
        grand[split] = (n_img, cnt)
        print(f"[{split}] 이미지={n_img}  bbox={sum(cnt.values())}")
        for cid in sorted(REMAP.values()):
            print(f"    {DST_NAMES[cid]:<10}(id={cid}): {cnt.get(cid, 0)}")

    n_cache = clear_caches()
    print(f"\n*.cache 삭제: {n_cache}")


if __name__ == "__main__":
    main()
