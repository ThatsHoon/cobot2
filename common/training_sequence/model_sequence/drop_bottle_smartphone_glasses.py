#!/usr/bin/env python3
"""drop_bottle_smartphone_glasses.py — bottle/smartphone/glasses 를 활성 split 에서 제거.

이전 10 classes:
  0=shaker, 1=bottle, 2=toy_block, 3=plate, 4=smartphone, 5=glasses,
  6=apple, 7=pear, 8=orange, 9=banana

이후 7 classes:
  0=shaker, 1=toy_block, 2=plate, 3=apple, 4=pear, 5=orange, 6=banana

흐름:
  1. images/<split>/{bottle,smartphone,glasses}_*.jpg + 대응 라벨 →
     data/backup/<class>/{images,labels}/<split>/
  2. 남은 라벨에 대해 클래스 ID 리맵:
     {0:0, 2:1, 3:2, 6:3, 7:4, 8:5, 9:6}; {1,4,5} 는 drop (안전망)
  3. *.cache 삭제
"""
from __future__ import annotations
import shutil
from pathlib import Path

DST_ROOT = Path("/home/hoon/backup_extracted/backup/data")
DROP_PREFIXES = ["bottle", "smartphone", "glasses"]
SPLITS = ["train", "valid", "test"]

OLD2NEW = {0: 0, 2: 1, 3: 2, 6: 3, 7: 4, 8: 5, 9: 6}
DROP_OLD = {1, 4, 5}


def move_class_files(prefix: str):
    moved = {"train": 0, "valid": 0, "test": 0}
    for split in SPLITS:
        img_src = DST_ROOT / "images" / split
        lbl_src = DST_ROOT / "labels" / split
        img_dst = DST_ROOT / "backup" / prefix / "images" / split
        lbl_dst = DST_ROOT / "backup" / prefix / "labels" / split
        img_dst.mkdir(parents=True, exist_ok=True)
        lbl_dst.mkdir(parents=True, exist_ok=True)
        for img in list(img_src.glob(f"{prefix}_*.jpg")):
            lbl = lbl_src / f"{img.stem}.txt"
            shutil.move(str(img), str(img_dst / img.name))
            if lbl.exists():
                shutil.move(str(lbl), str(lbl_dst / lbl.name))
            moved[split] += 1
    return moved


def remap_labels():
    stats = {"files": 0, "lines_in": 0, "remapped": 0, "dropped": 0}
    for split in SPLITS:
        lbl_dir = DST_ROOT / "labels" / split
        for lbl in lbl_dir.glob("*.txt"):
            stats["files"] += 1
            new_lines = []
            for line in lbl.read_text().strip().splitlines():
                parts = line.split()
                if len(parts) != 5:
                    continue
                stats["lines_in"] += 1
                old_cls = int(parts[0])
                if old_cls in DROP_OLD or old_cls not in OLD2NEW:
                    stats["dropped"] += 1
                    continue
                new_cls = OLD2NEW[old_cls]
                stats["remapped"] += 1
                new_lines.append(f"{new_cls} {parts[1]} {parts[2]} {parts[3]} {parts[4]}")
            if new_lines:
                lbl.write_text("\n".join(new_lines) + "\n")
            else:
                # 라벨 비면 빈 .txt 유지 (negative sample) — 그러나 이번엔 활성 데이터에
                # bottle/smartphone/glasses 만 있는 이미지는 위 단계에서 이미 backup 으로
                # 옮겨졌으므로, 빈 라벨이 되는 경우는 없어야 함.
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
        print(f"[move {prefix:<10}] train={moved['train']}  valid={moved['valid']}  test={moved['test']}")

    print()
    s = remap_labels()
    print(f"[remap] files={s['files']}  lines_in={s['lines_in']}  "
          f"remapped={s['remapped']}  dropped={s['dropped']}")

    n_cache = clear_caches()
    print(f"[cache] removed *.cache: {n_cache}")


if __name__ == "__main__":
    main()
