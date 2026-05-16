"""
Roboflow Universe 5개 데이터셋을 다운받아 우리 5-class 구조로 병합한다.

CLASS_NAMES = ["plate", "tissue", "smartphone", "remote", "glasses", "toy_block", "shaker"]   # ID 0~6

각 외부 데이터셋의 라벨 클래스 이름을 우리 클래스명에 매핑하고
나머지 클래스는 무시(라벨 행 drop)한다. 이미지는 그대로 복사.

사용:
    export ROBOFLOW_API_KEY="..."
    python3 download_datasets.py
"""

import os
import re
import shutil
import sys
import yaml
from pathlib import Path
from roboflow import Roboflow

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DOWNLOAD_DIR = BASE_DIR / "_roboflow_cache"

CLASS_NAMES = ["plate", "tissue", "smartphone", "remote", "glasses", "toy_block", "shaker"]
NAME2ID = {n: i for i, n in enumerate(CLASS_NAMES)}

# ─ 데이터셋 정의 ──────────────────────────────────────────────────────────
# class_map: 외부 클래스명(소문자) → 우리 클래스명(또는 None=drop)
DATASETS = [
    {
        "tag":       "plate",
        "workspace": "ata-ghofg",
        "project":   "bowls-vs-plates",
        "class_map": {
            "plate":  "plate",
            "plates": "plate",
            "bowl":   None,
            "bowls":  None,
        },
    },
    {
        "tag":       "tissue",
        "workspace": "mymap",
        "project":   "-tissue-quality",
        "class_map": {
            "tissue":     "tissue",
            "tissues":    "tissue",
            "tissue_box": "tissue",
            "toilet_paper":"tissue",
        },
    },
    {
        "tag":       "smartphone",
        "workspace": "pryexam",
        "project":   "smart-phone-jyvdu",
        "class_map": {
            "smart-phone": "smartphone",
            "smartphone":  "smartphone",
            "smart_phone": "smartphone",
            "phone":       "smartphone",
            "mobile":      "smartphone",
            "celular":     "smartphone",   # 포르투갈/스페인어
            "movil":       "smartphone",
            "telefono":    "smartphone",
        },
    },
    {
        "tag":       "remote",
        "workspace": "data-sets-ufvph",
        "project":   "remote-as3zm",
        "class_map": {
            "remote":         "remote",
            "remote_control": "remote",
            "remotecontrol":  "remote",
            "tv-remote":      "remote",
        },
    },
    {
        "tag":       "glasses",
        "workspace": "khaled-qwwx7",
        "project":   "glasses-kwmgc",
        "class_map": {
            "glasses":     "glasses",
            "eyeglasses":  "glasses",
            "sunglasses":  None,
        },
    },
    {
        "tag":       "toy_block",
        "workspace": "ps2-controller",
        "project":   "duplo-incomplete",
        "class_map": {
            # 실제 클래스명 확인 전 폭넓게 매핑 (부분일치 fallback도 작동)
            "duplo":      "toy_block",
            "block":      "toy_block",
            "blocks":     "toy_block",
            "brick":      "toy_block",
            "bricks":     "toy_block",
            "lego":       "toy_block",
            "toy":        "toy_block",
            "toy_block":  "toy_block",
        },
    },
]


def get_api_key() -> str:
    key = os.environ.get("ROBOFLOW_API_KEY", "").strip()
    if not key:
        print("[ERROR] ROBOFLOW_API_KEY 환경변수 미설정", file=sys.stderr)
        sys.exit(1)
    return key


def latest_version(project) -> int:
    """프로젝트의 사용 가능한 가장 큰 버전 번호. 못 찾으면 1."""
    try:
        versions = project.versions()
        if versions:
            nums = []
            for v in versions:
                # version id 가 'workspace/project/N' 형태
                m = re.search(r"/(\d+)$", str(v.id))
                if m:
                    nums.append(int(m.group(1)))
            if nums:
                return max(nums)
    except Exception as e:
        print(f"  [WARN] 버전 자동 탐색 실패: {e}")
    return 1


def download_dataset(rf: Roboflow, ds_def: dict) -> Path | None:
    """Roboflow 에서 yolov8 형식으로 다운로드. 다운된 디렉토리 반환."""
    tag = ds_def["tag"]
    print(f"\n[{tag}] {ds_def['workspace']}/{ds_def['project']}")
    try:
        proj = rf.workspace(ds_def["workspace"]).project(ds_def["project"])
    except Exception as e:
        print(f"  [ERROR] 프로젝트 접근 실패: {e}")
        return None

    ver_num = ds_def.get("version") or latest_version(proj)
    print(f"  버전: {ver_num}")

    out_dir = DOWNLOAD_DIR / tag
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    cwd = os.getcwd()
    try:
        os.chdir(out_dir)
        version = proj.version(ver_num)
        ds = version.download("yolov8")
        downloaded = Path(ds.location)
        print(f"  다운로드 완료: {downloaded}")
        return downloaded
    except Exception as e:
        print(f"  [ERROR] 다운로드 실패: {e}")
        return None
    finally:
        os.chdir(cwd)


def remap_label_file(src_label: Path, dst_label: Path,
                     ext_id_to_our_id: dict) -> int:
    """라벨 파일의 클래스 ID 를 우리 ID 로 재매핑. (변환된 줄 수 반환)"""
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
            continue   # 무시할 클래스
        out_lines.append(f"{new_id} {' '.join(parts[1:5])}")
    dst_label.write_text("\n".join(out_lines))
    return len(out_lines)


def merge_dataset(downloaded: Path, ds_def: dict, stats: dict):
    """다운된 yolov8 데이터셋을 data/ 로 병합."""
    tag = ds_def["tag"]
    yaml_path = downloaded / "data.yaml"
    if not yaml_path.exists():
        print(f"  [ERROR] data.yaml 없음 in {downloaded}")
        return

    with open(yaml_path) as f:
        cfg = yaml.safe_load(f)
    ext_names = cfg.get("names", [])
    if isinstance(ext_names, dict):
        ext_names = [ext_names[k] for k in sorted(ext_names.keys())]

    # 외부 클래스 ID → 우리 클래스 ID
    cmap = {k.lower(): v for k, v in ds_def["class_map"].items()}
    ext_id_to_our_id = {}
    for i, name in enumerate(ext_names):
        nm = name.lower().strip().replace(" ", "_")
        # 직접 매칭
        target = cmap.get(nm)
        # 부분 매칭 fallback (예: "tissue_box" 가 cmap 에 없어도 "tissue" 로)
        if target is None and nm not in cmap:
            for k, v in cmap.items():
                if k in nm or nm in k:
                    target = v
                    break
        if target:
            ext_id_to_our_id[i] = NAME2ID[target]

    print(f"  외부 클래스: {ext_names}")
    print(f"  매핑(외부ID→우리ID): {ext_id_to_our_id}")

    if not ext_id_to_our_id:
        print(f"  [WARN] 사용 가능한 클래스 매핑 없음 — 스킵")
        return

    # split 별 병합
    SPLIT_MAP = {"train": "train", "valid": "valid", "test": "test"}
    for src_split, dst_split in SPLIT_MAP.items():
        # roboflow yolov8 export 구조: train/images, train/labels
        src_img_dir = downloaded / src_split / "images"
        src_lbl_dir = downloaded / src_split / "labels"
        # 일부 export 는 valid 가 없을 수 있음 → 스킵
        if not src_img_dir.exists():
            continue

        dst_img_dir = DATA_DIR / "images" / dst_split
        dst_lbl_dir = DATA_DIR / "labels" / dst_split
        dst_img_dir.mkdir(parents=True, exist_ok=True)
        dst_lbl_dir.mkdir(parents=True, exist_ok=True)

        copied = 0
        kept_lines = 0
        for img_path in sorted(src_img_dir.iterdir()):
            if img_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                continue
            # 파일명 충돌 방지: prefix 추가
            new_name = f"{tag}_{img_path.name}"
            dst_img = dst_img_dir / new_name
            dst_lbl = dst_lbl_dir / (Path(new_name).stem + ".txt")

            shutil.copy2(img_path, dst_img)
            src_lbl = src_lbl_dir / (img_path.stem + ".txt")
            n = remap_label_file(src_lbl, dst_lbl, ext_id_to_our_id)

            # 라벨이 비어있는(우리 클래스 0개) 이미지는 negative sample 로 유지
            copied += 1
            kept_lines += n

        stats[(tag, dst_split)] = {"images": copied, "labels": kept_lines}
        print(f"  {dst_split:5s}: {copied:4d} 장 복사, {kept_lines:4d} 라벨 행 유지")


def main():
    api_key = get_api_key()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for split in ["train", "valid", "test"]:
        (DATA_DIR / "images" / split).mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "labels" / split).mkdir(parents=True, exist_ok=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    rf = Roboflow(api_key=api_key)
    stats = {}

    for ds_def in DATASETS:
        downloaded = download_dataset(rf, ds_def)
        if downloaded is None:
            continue
        merge_dataset(downloaded, ds_def, stats)

    # 최종 통계
    print("\n" + "=" * 70)
    print("  병합 완료 — split 별 클래스 분포")
    print("=" * 70)
    for split in ["train", "valid", "test"]:
        img_dir = DATA_DIR / "images" / split
        lbl_dir = DATA_DIR / "labels" / split
        n_img = len(list(img_dir.glob("*.[jp][pn]g")))
        cls_count = [0] * len(CLASS_NAMES)
        n_lbl = 0
        for lbl in lbl_dir.glob("*.txt"):
            for line in lbl.read_text().splitlines():
                p = line.split()
                if len(p) >= 5:
                    try:
                        cls_count[int(p[0])] += 1
                        n_lbl += 1
                    except (ValueError, IndexError):
                        pass
        print(f"\n  [{split}] images={n_img}  labels={n_lbl}")
        for i, n in enumerate(CLASS_NAMES):
            print(f"    {i} {n:<12} {cls_count[i]:>5}")

    print("\n  완료. data/ 에 병합됨.")
    print(f"  로보플로우 캐시: {DOWNLOAD_DIR} (필요시 삭제 가능)")


if __name__ == "__main__":
    main()
