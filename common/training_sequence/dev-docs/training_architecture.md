# 학습 아키텍처 및 방법론

> 7-class object detection (YOLO11s) 학습 파이프라인 문서.
> 대상 코드: `/home/rokey/backup/model_sequence/train.py`
> 데이터: `/home/rokey/backup/data` (10-class → cup/tissue/bottle/smartphone/glasses 제거 후 **7-class**)
> 배포: `/home/rokey/cobot_ws/src/cobot2/object_detection/resource`

---

## 1. 클래스 체계

| ID | 클래스 | 비고 |
|---|---|---|
| 0 | shaker | 양념통 (소금/후추) |
| 1 | toy_block | 장난감 블록 (Duplo) |
| 2 | plate | 접시 |
| 3 | apple | 사과 |
| 4 | pear | 배 |
| 5 | orange | 오렌지 |
| 6 | banana | 바나나 |

배포 시 `class_name.json` 으로 직렬화되어 `cobot2/object_detection/resource/` 에 동기화됨.

---

## 2. 디렉토리 구조

```
backup/                                  # 워크스페이스 루트
├── data/                                # 통합 데이터셋
│   ├── data.yaml                        # ultralytics 학습용 설정 (nc, names, path)
│   ├── images/{train,valid,test}/       # 1089 / 133 / 133 imgs (.jpg)
│   ├── labels/{train,valid,test}/       # YOLO bbox 형식 (.txt)
│   └── backup/                          # 잉여·드롭된 클래스 보관소
│       ├── <active_class>/              # 200 cap 초과분 (bottle, smartphone, ...)
│       ├── <dropped_class>/{images,labels}/{train,valid,test}/    # 제거된 클래스의 이전 활성 데이터
│       └── old_*/                       # 이전 머지 스냅샷
│
├── model_sequence/                      # 학습 코드 + 산출물
│   ├── train.py                         # 학습 메인
│   ├── prepare_dataset.py               # Roboflow + 로컬 + fruits 통합 빌드
│   ├── integrate_fruits.py              # 헬퍼: fruits 데이터 통합
│   ├── integrate_real_data.py           # 헬퍼: 로봇 캡처 segmentation polygon → bbox 통합
│   ├── topup_classes.py                 # 헬퍼: 백업 풀에서 부족 클래스 보강
│   ├── drop_*.py                        # 헬퍼: 클래스 제거 + ID 재번호
│   ├── cobot.yaml                       # train.py 자동 생성 (gitignore)
│   ├── model_registry.json              # 버전 메타 + 메트릭
│   ├── yolo11s.pt / yolov8s.pt          # 사전학습 가중치
│   └── runs/                            # 학습 산출물 (gitignore)
│       ├── best.pt                      # 누적 best 사본
│       └── v{N}_cobot_<MMDD_HHMM>/      # 버전별 run
│
└── dev-docs/                            # 본 문서
```

**원칙**:
- 깊은 중첩 회피 (3-4 단계 이내)
- 단일 파일로 충분한 기능은 디렉토리화하지 않음
- 헬퍼 스크립트는 `model_sequence/` 평탄 배치

---

## 3. 데이터 구성

### 3.1 소스별 분포 (총 1355 이미지, 3901 bbox)

| 소스 | 이미지 | bbox | 평균 bbox/img | 특성 |
|---|---|---|---|---|
| roboflow | 600 | 607 | 1.01 | 단일 클래스, 인터넷 수집, 깨끗한 배경 |
| fruits | 377 | 1040 | 2.76 | multi-class fruits (Roboflow `tzach/fruits-ekcjm`) |
| real | 378 | 2254 | **5.96** | RealSense top-down 캡처, multi-object 장면 |

**파일명 prefix 로 소스 식별**:
- `<class_name>_*.jpg` → roboflow (예: `bottle_xxx.jpg`)
- `fruits_*.jpg` → fruits 데이터셋
- `real_*.jpg` → 로봇 환경 캡처

### 3.2 클래스 × Split bbox 분포

| id | class | train | valid | test | total |
|---|---|---|---|---|---|
| 0 | shaker | 322 | 38 | 38 | 398 |
| 1 | toy_block | 646 | 71 | 76 | 793 |
| 2 | plate | 482 | 63 | 59 | 604 |
| 3 | apple | 368 | 44 | 43 | 455 |
| 4 | pear | 448 | 53 | 58 | 559 |
| 5 | orange | 413 | 56 | 50 | 519 |
| 6 | banana | 466 | 51 | 56 | 573 |
| | **합계** | 3145 | 376 | 380 | **3901** |

- Split 비율: 80/10/10 (≈ 1089/133/133 imgs)
- 클래스 균형: min/max ratio = 1:2.0 (mild)
- 변동계수 CV = 21% (정상 detection 데이터셋 수준)

### 3.3 클래스 × 소스 기여도

| class | roboflow | fruits | real | real 비중 |
|---|---|---|---|---|
| shaker | 200 | 0 | 198 | 50% |
| toy_block | 207 | 0 | 586 | **74%** |
| plate | 200 | 0 | 404 | 67% |
| apple | 0 | 302 | 153 | 34% |
| pear | 0 | 265 | 294 | 53% |
| orange | 0 | 230 | 289 | 56% |
| banana | 0 | 243 | 330 | 58% |

→ toy_block, plate 는 real-heavy 클래스. 실제 환경 robustness 양호. 그러나 polygon→bbox 변환된 real 라벨이 dominant 신호.

### 3.4 Bbox quality (real_data)

real_data 라벨은 YOLO segmentation polygon (가변 길이) 으로 export 되어, `integrate_real_data.py:poly_to_bbox()` 에서 **axis-aligned min/max** 로 bbox 변환.

| class | tightness (poly area / bbox area) |
|---|---|
| pear, orange, apple | 0.77~0.79 (✅ 매우 tight, 원형) |
| plate | 0.76 (✅ tight) |
| shaker | 0.71 (◯ 보통) |
| toy_block | 0.65 (◯ 보통) |
| banana | **0.37** (⚠ loose, 길고 굽은 형태의 본질적 한계) |

→ 평균 0.68 (COCO 0.60 보다 높음) — bbox 품질 자체는 양호.
→ banana 만 형태 특성상 loose. 사람이 직접 그려도 동일 (axis-aligned bbox 의 본질적 한계).

---

## 4. 학습 파이프라인 (train.py)

### 4.1 흐름

```
1. argparse              ──▶  args (mode, epochs, patience, base_model, ...)
2. setup_log_file()      ──▶  logs/train_<ts>.log + stdout/stderr tee
3. cobot.yaml 자동 생성   ──▶  data.yaml 등가물을 BASE_DIR 에 작성
4. validate_split()      ──▶  img↔label 매칭, class_id 범위, ann 형식 검증
5. ModelRegistry 로드    ──▶  model_registry.json 의 누적 버전·best 정보
6. data_fingerprint()    ──▶  split count + 파일명 md5 → 데이터 변경 자동 감지
7. TRAIN_MODE 분기:
     - new        : args.base_model (yolo11s.pt) 부터 새로 학습
     - resume     : runs/<run>/weights/last.pt 에서 이어 학습
     - more_data  : registry.best_pt() 로 warm-start (incremental learning)
8. 콜백 등록             ──▶  on_fit_epoch_end (1줄 진행 막대), on_train_end
9. model.train(**HYPER)  ──▶  ultralytics 학습 실행
10. eval_model.val(split="test")
11. compute_center_error()  ──▶  로봇 파지 직결 지표 (GT-pred 중심 픽셀거리)
12. registry.register()  ──▶  메트릭·환경·git_commit 기록 + best 자동 갱신
13. NEW BEST 시:
     - runs/best.pt 갱신
     - OD_RESOURCE/best.pt 자동 배포
     - class_name.json + class_name_tool.json 동기화
14. save_metrics_visualization()  ──▶  metrics_summary.png + per_class_ap.png
```

### 4.2 사용

```bash
# 기본 학습 (epochs=100, yolo11s.pt 베이스)
python3 train.py

# 빠른 sanity check
python3 train.py --epochs 3

# 이어 학습 (interrupted run 복구)
python3 train.py --mode resume --resume-run v9_cobot_0507_1703

# 데이터 추가 후 incremental 학습 (best.pt warm-start)
python3 train.py --mode more_data

# 다른 베이스 모델 (롤백)
python3 train.py --base-model yolov8s.pt

# 학습만, 평가/등록 스킵 (디버깅)
python3 train.py --no-eval
```

---

## 5. 모델 아키텍처

### 5.1 베이스 모델: YOLO11s

- **Parameters**: ~9.4M
- **GFLOPs (640×640)**: ~21.5
- **Backbone**: C3k2 blocks (YOLOv8 의 C2f 개선)
- **Head**: anchor-free, decoupled (cls/box/dfl 분리)
- **Loss**: BCE (classification) + CIoU (box) + DFL (distribution focal loss for box)

### 5.2 이전 모델 비교 (registry 기록)

| 베이스 | best fitness 도달 | 비고 |
|---|---|---|
| yolov8s.pt | 0.6496 (v6) | 8-class era |
| **yolo11s.pt** | **0.7592 (v9)** | yolo11 도입으로 큰 점프 |

→ 신 학습은 모두 yolo11s 기반. yolov8s.pt 는 롤백 대비용.

---

## 6. 하이퍼파라미터 (HYPER)

### 6.1 Optimization

| 파라미터 | 값 | 근거 |
|---|---|---|
| `epochs` | 100 | early stop 으로 보통 50~80 epoch 에서 수렴 |
| `patience` | 20 | 20 epoch 개선 없으면 조기 종료 |
| `batch` | -1 (auto) | GPU 메모리 기준 자동 결정 (보통 16~32) |
| `imgsz` | 640 | yolo11s pretrained 일관성 |
| `optimizer` | AdamW | 작은 dataset + transfer learning 에 SGD 보다 안정 |
| `lr0` | 0.0005 | YOLO default 0.001 보다 보수적 (transfer 안정성) |
| `lrf` | 0.01 | 최종 LR = lr0 × lrf = 5e-6 |
| `weight_decay` | 0.001 | 작은 dataset (1089장) 정규화 강화 |
| `warmup_epochs` | 3 | LR 워밍업 |
| `warmup_momentum` | 0.8 | |
| `cos_lr` | True | cosine LR schedule |
| `freeze` | 5 | 앞 5층 backbone 동결, 뒤 절반 + head 학습 (real_data top-down view 적응) |
| `dropout` | 0.1 | 작은 dataset mild regularization |
| `label_smoothing` | 0.1 | 7-class mild imbalance overconfidence 억제 |
| `amp` | True | 혼합정밀도 (속도+VRAM) |
| `cache` | "ram" | 1.6GB 정도 → RAM 캐시 안전 |

### 6.2 Augmentation

#### 색상 (per-image, online stochastic)
| 파라미터 | 값 | 의미 |
|---|---|---|
| `hsv_h` | 0.015 | hue ±1.5%, fruits 색 정체성 보존 |
| `hsv_s` | **0.4** | saturation ±40%, 색 기반 클래스 구분 보존 (default 0.7 → 0.4) |
| `hsv_v` | 0.4 | brightness ±40%, 조명 변화 모사 |

#### 기하 (per-image)
| 파라미터 | 값 | 의미 |
|---|---|---|
| `degrees` | 15.0 | rotation ±15°, top-down 환경 적합 |
| `translate` | 0.1 | translation ±10% |
| `scale` | 0.5 | scale ±50%, 카메라 거리 변화 모사 |
| `shear`, `perspective` | 0.0 | top-down 엔 불필요 |
| `flipud` | 0.2 | 위아래 flip 20% (top-down 시점에선 OK) |
| `fliplr` | 0.5 | 좌우 flip 50% |
| `multi_scale` | **True** | 매 10 batch 마다 imgsz × random[0.5~1.5] (**카메라 거리 30~50cm 변동 학습**) |
| `erasing` | **0.2** | random erase 20% (default 0.4 → 0.2 명시화) |

#### 합성 (multi-image)
| 파라미터 | 값 | 의미 |
|---|---|---|
| `mosaic` | 1.0 | 4장 합성 100% — 작은 dataset 다양성 폭증 (×4 effective bbox/epoch) |
| `mixup` | **0.05** | alpha-blend 5% (real_data 5.96 bbox/img 와 합성 시 과부하 → 15% → 5% 완화) |
| `copy_paste` | **0.0** | 비활성화 (segmentation mask 부재 → bbox 영역 잘라 붙이면 부정확 합성) |
| `close_mosaic` | 15 | 마지막 15 epochs 는 mosaic/mixup/copy_paste 모두 OFF (안정화) |

### 6.3 증강에 따른 effective bbox 노출량

per-epoch:
- mosaic phase (epochs 1~85): raw × 3.5 → 약 11,000 bbox / epoch
- close_mosaic phase (epochs 86~100): raw × 1.0 → 3,145 bbox / epoch

100 epochs 누적: 약 **985,000 bbox 노출** (raw 3,145 × 313 평균 multiplier)

---

## 7. 평가 지표

### 7.1 학습 중 (validation split)
- `metrics/mAP50(B)`: IoU 0.5 mAP
- `metrics/mAP50-95(B)`: IoU 0.5~0.95 평균 mAP

### 7.2 학습 후 (test split)
- mAP@50, mAP@50-95
- Precision, Recall, F1
- **fitness = 0.1 × mAP50 + 0.9 × mAP50-95** (best 결정 기준, ultralytics 와 동일)
- FPS (50회 평균, warmup 30회)
- **center_err_px**: GT-pred bbox 중심 픽셀 거리 (로봇 파지 직결, `compute_center_error()`)
- per_class_ap50

### 7.3 출력 파일 (`runs/v{N}_cobot_<ts>/`)
- `weights/best.pt`, `weights/last.pt`, `weights/epoch{20,40,60,80}.pt`
- `results.csv` (epoch별 loss, metric)
- `metrics_summary.png` — 한 장 종합 요약
- `per_class_ap.png` — 클래스별 AP@50 막대그래프
- `test_confusion_matrix.png` 등 ultralytics 자동 생성물 복사

---

## 8. ModelRegistry (model_registry.json)

### 8.1 역할
1. 누적 버전 기록 (v1, v2, ...)
2. 데이터 fingerprint 변경 자동 감지
3. fitness 기준 best 자동 갱신
4. 환경 (python, torch, cuda, ultralytics 버전) 스냅샷
5. git_commit hash 기록

### 8.2 버전 결정
- `next_version()` = `f"v{len(versions) + 1}"`
- `make_run_name(version)` = `f"{version}_cobot_{datetime:%m%d_%H%M}"`

### 8.3 데이터 변경 감지
```python
data_fingerprint(data_dir) → {
    "{split}_count": int,
    "{split}_hash": str,    # 파일명 sorted join 의 md5[:8]
}
detect_data_change(current_fp) → (changed: bool, msg: str)
```

→ split 별 이미지 수 또는 파일명 셋 변경 시 감지. 변경 없으면 동일 데이터로 학습 중복 방지.

### 8.4 best 갱신 트리거
- `is_best = score > prev_best_fitness`
- True 시:
  - 다른 모든 versions 의 `is_best = False`
  - `runs/best.pt` 갱신
  - `OD_RESOURCE/best.pt` + `class_name.json` + `class_name_tool.json` 갱신

### 8.5 versioned 가중치 보존
- `versions/v{N}_cobot_<ts>.pt` (`registry.versions_dir`) 에 모든 학습 가중치 영구 보관
- `runs/<run>/weights/` 는 `.gitignore` 에 의해 정리 가능

---

## 9. 학습 모드

### 9.1 `--mode new` (기본)
- 베이스: `args.base_model` (default `yolo11s.pt`)
- 모든 weight 새로 시작 + freeze 처음 5층
- 데이터 큰 변화 시 권장

### 9.2 `--mode resume`
- 베이스: `runs/{resume_run}/weights/last.pt`
- 동일 run_name, exist_ok=True
- 학습 중단 복구용

### 9.3 `--mode more_data` (incremental)
- 베이스: `registry.best_pt_path()` 또는 `--more-data-base-pt`
- 새 version 으로 등록되지만 warm-start
- 데이터 추가 후 빠른 적응

---

## 10. 데이터 추가 워크플로우

### 10.1 새 클래스/데이터셋 추가
1. `prepare_dataset.py` 의 `DATASETS` 리스트에 Roboflow workspace/project + class_map 추가
2. `CLASS_NAMES` 갱신 (prepare_dataset.py + train.py)
3. `python3 prepare_dataset.py` 실행 (또는 `--dry-run` 으로 카운트만 미리 보기)
4. `python3 train.py --mode new --epochs 3` sanity check
5. 본 학습 `python3 train.py`

### 10.2 로봇 캡처 데이터 추가 (segmentation polygon 형식)
- `integrate_real_data.py` 의 `REMAP` 갱신 후 실행
- polygon → axis-aligned bbox 자동 변환
- 80/10/10 split + class ID 리맵

### 10.3 클래스 제거
- `drop_<class>.py` 패턴: 활성 split 에서 backup 으로 이동 + 남은 라벨 ID 리맵
- `data.yaml` `nc, names` 갱신
- `train.py CLASS_NAMES` 갱신
- `prepare_dataset.py CLASS_NAMES + DATASETS` 갱신

### 10.4 클래스 데이터 보강 (top-up)
- `topup_classes.py` 패턴: backup 풀에서 부족분 샘플링 → active 로 이동
- 라벨 ID 자동 리맵
- 80/10/10 split

---

## 11. 배포 통합 (cobot2 ROS 2)

### 11.1 자동 배포 경로
```
runs/<run>/weights/best.pt
  ──▶ runs/best.pt                                   (누적 best)
  ──▶ versions/<run>.pt                              (영구 보관)
  ──▶ /home/rokey/cobot_ws/src/cobot2/object_detection/resource/best.pt
  ──▶ .../resource/class_name.json
  ──▶ .../resource/class_name_tool.json              (pick_and_place_text 용)
```

### 11.2 production 코드 의존성
- `cobot2/object_detection/yolo.py` 가 `class_name.json` + `best.pt` 로드
- `pick_and_place_text` test 가 `class_name_tool.json` 사용

→ best 갱신 시 ROS 2 패키지 재빌드 없이 weight 만 hot swap 가능.

---

## 12. 로깅 + 재현성

### 12.1 자동 로그 파일
- `logs/train_<YYYYMMDD_HHMMSS>.log` (stdout + stderr + ultralytics LOGGER)
- `--no-log-file` 로 비활성화 가능

### 12.2 재현성 제어
- `seed=42, deterministic=True`
- `git_commit` 기록 (registry)
- 환경 스냅샷 (python/torch/cuda/ultralytics 버전)
- 데이터 fingerprint (split count + 파일명 md5)

→ 같은 commit + 같은 데이터 + 같은 args = 같은 결과.

---

## 13. 주의 사항

1. **경로 하드코딩**: `DATA_DIR = /home/rokey/backup/data`, `OD_RESOURCE = /home/rokey/cobot_ws/...` — 다른 머신에서 학습 시 심볼릭 링크 (`ln -s`) 또는 코드 수정 필요.

2. **`cobot.yaml` 자동 생성**: train.py 매 실행 시 BASE_DIR 에 새로 작성됨. `.gitignore` 에 등록되어 있음. **`data/data.yaml` 과는 별개 파일**.

3. **`runs/`, `versions/`, `logs/` 모두 gitignore**. 영속화하려면 별도 백업.

4. **`*.cache` (ultralytics label cache)**: 라벨 변경 시 자동 무효화되나, 안전하게 `data/labels/*.cache` 삭제 후 재학습 권장. 헬퍼 스크립트들이 자동으로 정리.

5. **ROS_DOMAIN_ID 충돌**: production 학습 머신과 로봇이 같은 네트워크에 있을 시 ROS 2 DDS 가 cobot2 노드와 충돌할 수 있음. 학습 머신에서 `unset ROS_DOMAIN_ID` 권장.

6. **GPU VRAM**: yolo11s @ imgsz 640, batch auto → 8GB+ VRAM 권장. CPU 학습은 매우 느림 (warning 출력됨).

---

## 14. 향후 개선 후보

| 항목 | 우선순위 | 비고 |
|---|---|---|
| polygon-aware loss (real_data segmentation 활용) | 낮음 | YOLO11-seg 으로 전환 시 |
| WeightedRandomSampler (클래스 균형) | 낮음 | 현재 1:2 mild — 필요시 |
| TensorRT export (`*.engine`) | 보통 | 추론 속도 ↑ (production) |
| MLflow 통합 | 낮음 | 현재 model_registry.json 으로 충분 |
| Roboflow 라벨 자동 동기화 (Active Learning) | 보통 | 로봇 신규 캡처 → annotate → re-train 자동화 |
| imgsz 720 실험 | 보통 | small object (멀리 있는 fruits) AP 향상 가능 |

---

*마지막 업데이트: 2026-05-08*
*작성: model_sequence/train.py + 데이터 빌드 헬퍼 코드 분석 기반*
