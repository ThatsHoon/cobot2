"""merge_local_dataset.py — 로컬 Roboflow YOLOv8 export 를 data/ 에 병합.

기존 download_datasets.py 와 동일한 디렉토리 규약 (data/{images,labels}/{train,valid,test})
파일명 충돌 방지: 타깃 클래스명을 prefix 로 붙임 (예: shaker_xxx.jpg).
라벨 ID 는 외부 클래스명 → 우리 CLASS_NAMES 인덱스로 자동 remap.

사용:
    python3 merge_local_dataset.py \\
        --source ~/Downloads/shaker --target shaker

옵션:
    --source PATH       로컬 Roboflow yolov8 export 디렉토리 (data.yaml 포함)
    --target NAME       우리 CLASS_NAMES 의 타깃 클래스명 (예: shaker)
    --map "ext:our,..." 외부 클래스명 → 타깃 매핑 (지정 안 하면 모든 외부 클래스를 --target 으로)
    --copy-mode {copy,symlink}  파일 복사 방식 (기본: copy)
    --dry-run           실제 복사 없이 카운트만
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Dict, Optional

import yaml


# train.py / download_datasets.py 와 동일하게 유지
CLASS_NAMES = ["plate", "tissue", "smartphone", "remote", "glasses",
               "toy_block", "shaker"]
NAME2ID = {n: i for i, n in enumerate(CLASS_NAMES)}

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True,
                    help="Roboflow yolov8 export 폴더 (data.yaml 포함)")
    ap.add_argument("--target", required=True,
                    help=f"타깃 클래스명 (CLASS_NAMES={CLASS_NAMES} 중 하나)")
    ap.add_argument("--map", default="",
                    help='외부→우리 클래스 매핑 "ext1:our1,ext2:our2,..."  '
                         '비우면 모든 외부 클래스를 --target 으로')
    ap.add_argument("--copy-mode", choices=["copy", "symlink"], default="copy")
    ap.add_argument("--dry-run", action="store_true")
    return ap.parse_args()


def parse_class_map(spec: str, default_target: str) -> Dict[str, str]:
    """'ext1:our1,ext2:our2' 또는 빈 문자열 → dict."""
    if not spec.strip():
        return {}    # caller 가 default 사용
    out = {}
    for tok in spec.split(","):
        if not tok.strip():
            continue
        if ":" not in tok:
            raise ValueError(f"잘못된 매핑 형식: {tok!r} (ext:our 형식)")
        k, v = tok.split(":", 1)
        out[k.strip().lower()] = v.strip()
    return out


def build_ext_id_to_our_id(ext_names: list, cmap: Dict[str, str],
                           default_our: str) -> Dict[int, int]:
    """외부 클래스 ID(0..N) → 우리 CLASS_NAMES ID."""
    result = {}
    for i, name in enumerate(ext_names):
        nm = str(name).lower().strip().replace(" ", "_")
        # 1) 정확 매칭
        target = cmap.get(nm)
        # 2) 부분 매칭 fallback
        if target is None and cmap:
            for k, v in cmap.items():
                if k in nm or nm in k:
                    target = v
                    break
        # 3) cmap 비어있으면 default_our 사용
        if target is None and not cmap:
            target = default_our
        if target and target in NAME2ID:
            result[i] = NAME2ID[target]
    return result


def remap_label_file(src_label: Path, dst_label: Path,
                     ext_id_to_our_id: Dict[int, int]) -> int:
    if not src_label.exists():
        dst_label.write_text("")
        return 0
    out_lines = []
    for line in src_label.read_text().splitlines():
        parts = line.strip().split()
        if len(parts) < 5:
            continue
        try:
            cid = int(parts[0])
        except ValueError:
            continue
        new_id = ext_id_to_our_id.get(cid)
        if new_id is None:
            continue
        out_lines.append(f"{new_id} {' '.join(parts[1:5])}")
    dst_label.write_text("\n".join(out_lines))
    return len(out_lines)


def main():
    args = parse_args()

    if args.target not in NAME2ID:
        print(f"[ERROR] --target {args.target!r} 는 CLASS_NAMES 에 없음", file=sys.stderr)
        print(f"        CLASS_NAMES = {CLASS_NAMES}", file=sys.stderr)
        sys.exit(1)

    src = args.source.expanduser().resolve()
    if not (src / "data.yaml").exists():
        print(f"[ERROR] {src}/data.yaml 없음 — 올바른 Roboflow 폴더인지 확인", file=sys.stderr)
        sys.exit(1)

    cfg = yaml.safe_load(open(src / "data.yaml"))
    ext_names = cfg.get("names", [])
    if isinstance(ext_names, dict):
        ext_names = [ext_names[k] for k in sorted(ext_names.keys())]
    print(f"[INFO] source={src}")
    print(f"[INFO] external classes: {ext_names}")
    print(f"[INFO] target='{args.target}' (id={NAME2ID[args.target]})")

    cmap = parse_class_map(args.map, args.target)
    if not cmap:
        print(f"[INFO] --map 미지정 → 모든 외부 클래스를 '{args.target}' 으로 매핑")
    ext_id_to_our_id = build_ext_id_to_our_id(ext_names, cmap, args.target)
    if not ext_id_to_our_id:
        print("[ERROR] 매핑 가능한 외부 클래스 없음", file=sys.stderr)
        sys.exit(1)
    print(f"[INFO] 매핑(ext→our): {ext_id_to_our_id}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SPLITS = ["train", "valid", "test"]
    stats = {}
    for split in SPLITS:
        sdir = src / split
        if not (sdir / "images").exists():
            print(f"[INFO] {split} 없음 — 스킵")
            continue
        dst_img = DATA_DIR / "images" / split
        dst_lbl = DATA_DIR / "labels" / split
        dst_img.mkdir(parents=True, exist_ok=True)
        dst_lbl.mkdir(parents=True, exist_ok=True)

        n_img = n_lbl_lines = 0
        for img_path in sorted((sdir / "images").iterdir()):
            if img_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                continue
            new_name = f"{args.target}_{img_path.name}"
            dst_i = dst_img / new_name
            dst_l = dst_lbl / (Path(new_name).stem + ".txt")
            src_l = sdir / "labels" / (img_path.stem + ".txt")

            if args.dry_run:
                pass
            else:
                if dst_i.exists():
                    dst_i.unlink()
                if args.copy_mode == "symlink":
                    dst_i.symlink_to(img_path)
                else:
                    shutil.copy2(img_path, dst_i)
                n = remap_label_file(src_l, dst_l, ext_id_to_our_id)
                n_lbl_lines += n
            n_img += 1
        stats[split] = (n_img, n_lbl_lines)
        print(f"  {split:5s}  images={n_img:>4}  labels={n_lbl_lines:>4}")

    print()
    print("=" * 60)
    print(f"  병합 완료 (target='{args.target}', dry-run={args.dry_run})")
    print("=" * 60)
    for split in SPLITS:
        if split not in stats:
            continue
        img_dir = DATA_DIR / "images" / split
        lbl_dir = DATA_DIR / "labels" / split
        n_imgs = sum(1 for _ in img_dir.glob("*.[jp][pn]g"))
        cls_count = [0] * len(CLASS_NAMES)
        for lbl in lbl_dir.glob("*.txt"):
            for ln in lbl.read_text().splitlines():
                p = ln.split()
                if len(p) >= 5:
                    try:
                        i = int(p[0])
                        if 0 <= i < len(CLASS_NAMES):
                            cls_count[i] += 1
                    except ValueError:
                        pass
        print(f"\n  [{split}] total images={n_imgs}")
        for i, n in enumerate(CLASS_NAMES):
            mark = " ← +" if i == NAME2ID[args.target] else "    "
            print(f"   {i} {n:<12} {cls_count[i]:>5}{mark}")


if __name__ == "__main__":
    main()
