#!/usr/bin/env python3
"""drop_cup_tissue.py — cup, tissue 클래스를 활성 split 에서 제거하고 클래스 ID 재번호.

이전: 12 classes [shaker, bottle, cup, toy_block, plate, tissue, smartphone, glasses,
                   apple, pear, orange, banana]
이후: 10 classes [shaker, bottle, toy_block, plate, smartphone, glasses,
                   apple, pear, orange, banana]

흐름:
  1. images/<split>/cup_*.jpg + 대응 라벨 → data/backup/cup/{images,labels}/<split>/
     images/<split>/tissue_*.jpg + 대응 라벨 → data/backup/tissue/{images,labels}/<split>/
  2. 남은 모든 라벨(.txt)에 대해 클래스 ID 리맵
     {0:0, 1:1, 3:2, 4:3, 6:4, 7:5, 8:6, 9:7, 10:8, 11:9}; 2/5 는 안전망(이미 이동됨)
  3. *.cache 삭제 (label set 변경됨)
"""
from __future__ import annotations
import shutil
from pathlib import Path

DST_ROOT = Path("/home/hoon/backup_extracted/backup/data")
DROP_PREFIXES = ["cup", "tissue"]
SPLITS = ["train", "valid", "test"]

OLD2NEW = {0: 0, 1: 1, 3: 2, 4: 3, 6: 4, 7: 5, 8: 6, 9: 7, 10: 8, 11: 9}
DROP_OLD = {2, 5}


def move_class_files(prefix: str):
    moved = {"train": 0, "valid": 0, "test": 0}
    for split in SPLITS:
        img_src = DST_ROOT / "images" / split
        lbl_src = DST_ROOT / "labels" / split
        img_dst = DST_ROOT / "backup" / prefix / "images" / split
        lbl_dst = DST_ROOT / "backup" / prefix / "labels" / split
        img_dst.mkdir(parents=True, exist_ok=True)
        lbl_dst.mkdir(parents=True, exist_ok=True)
        for img in img_src.glob(f"{prefix}_*.jpg"):
            lbl = lbl_src / f"{img.stem}.txt"
            shutil.move(str(img), str(img_dst / img.name))
            if lbl.exists():
                shutil.move(str(lbl), str(lbl_dst / lbl.name))
            moved[split] += 1
    return moved


def remap_labels():
    stats = {"files": 0, "lines": 0, "dropped": 0, "remapped": 0}
    for split in SPLITS:
        lbl_dir = DST_ROOT / "labels" / split
        for lbl in lbl_dir.glob("*.txt"):
            stats["files"] += 1
            new_lines = []
            for line in lbl.read_text().strip().splitlines():
                parts = line.split()
                if len(parts) != 5:
                    continue
                stats["lines"] += 1
                old_cls = int(parts[0])
                if old_cls in DROP_OLD:
                    stats["dropped"] += 1
                    continue
                if old_cls not in OLD2NEW:
                    stats["dropped"] += 1
                    continue
                new_cls = OLD2NEW[old_cls]
                stats["remapped"] += 1
                new_lines.append(f"{new_cls} {parts[1]} {parts[2]} {parts[3]} {parts[4]}")
            if new_lines:
                lbl.write_text("\n".join(new_lines) + "\n")
            else:
                # 라벨이 비면 negative sample 로 빈 .txt 유지
                lbl.write_text("")
    return stats


def clear_caches():
    n = 0
    for cache in (DST_ROOT / "labels").glob("*.cache"):
        cache.unlink()
        n += 1
    return n


def main():
    print(f"DST : {DST_ROOT}\n")

    for prefix in DROP_PREFIXES:
        moved = move_class_files(prefix)
        print(f"[move {prefix}] train={moved['train']}  valid={moved['valid']}  test={moved['test']}")

    print()
    stats = remap_labels()
    print(f"[remap] files={stats['files']}  lines={stats['lines']}  "
          f"remapped={stats['remapped']}  dropped={stats['dropped']}")

    n_cache = clear_caches()
    print(f"[cache] removed *.cache: {n_cache}")


if __name__ == "__main__":
    main()
