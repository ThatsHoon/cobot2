# 데이터셋 배치 가이드

## 1. 디렉토리 구조

```
data/
├── images/
│   ├── train/    ← 학습 이미지 (.jpg / .png)
│   ├── valid/    ← 검증 이미지
│   └── test/     ← 최종 평가 이미지
└── labels/
    ├── train/    ← train 이미지에 대응하는 .txt 라벨
    ├── valid/
    └── test/
```

**규칙**: 이미지와 라벨은 **파일명이 같아야** 한다.

```
images/train/IMG_0001.jpg  ↔  labels/train/IMG_0001.txt
images/valid/scene_42.png  ↔  labels/valid/scene_42.txt
```

## 2. 라벨 파일 형식 (YOLO)

각 줄에 한 객체.

```
<class_id> <cx> <cy> <w> <h>
```

| 필드 | 설명 |
|------|------|
| `class_id` | 클래스 인덱스 (아래 표) |
| `cx, cy` | bbox 중심 좌표 — **이미지 너비/높이로 정규화한 0~1 값** |
| `w, h`   | bbox 너비/높이 — 동일하게 0~1 정규화 |

### 클래스 ID

| ID | 클래스 (영문) | 한국어 |
|----|---------------|--------|
| 0  | pencil_case   | 필통 |
| 1  | toy_block     | 장난감블록 |
| 2  | plate         | 접시 |
| 3  | pepper_shaker | 후추통 |

### 예시

이미지 `images/train/IMG_0001.jpg` 안에 필통 1개, 접시 1개가 있을 때 → `labels/train/IMG_0001.txt`:

```
0 0.4521 0.6103 0.1820 0.2410
2 0.7715 0.4502 0.3010 0.3215
```

객체가 없는 이미지면 빈 `.txt` 파일을 두면 negative sample 로 사용된다.

## 3. 권장 데이터 분할

| split | 비율 | 클래스당 최소 |
|-------|------|---------------|
| train | 70~80% | 70~80 장 |
| valid | 10~15% | 10~15 장 |
| test  | 10~15% | 10~15 장 |

**같은 객체/세션의 frame 이 train/valid 에 섞이지 않도록** 캡처 세션 단위로 분리할 것 (data leakage 방지).

## 4. 데이터 수집 권장사항 (RealSense top-down)

- 카메라 각도: 로봇 작업 평면 위 30~50 cm, top-down ±15°
- 조명: 형광등 / 자연광 / 저조도 등 다양하게
- 배경: 작업 테이블 / 다른 물체와 함께 / 단독
- 객체 자세: 회전 360°, 부분 가림(occlusion) 케이스 포함
- 클래스당 최소 100 장 권장 (총 400 장+)

## 5. 라벨링 도구

- **Roboflow Universe** (web, 권장) — 데이터셋 export 시 YOLO 형식 선택
- **labelImg** (local) — 클래스 파일을 위 ID 순서로 작성
- **CVAT** (self-hosted)

## 6. 자동 검증

`train.ipynb` 의 §3 `validate_split()` 셀이 다음을 검사한다.

- 이미지 ↔ 라벨 파일명 매칭
- 클래스 ID 가 0~3 범위 안인지
- bbox 좌표가 0~1 범위 안인지
- 클래스별 분포 (불균형 경고)

## 7. Roboflow 자동 다운로드 (옵션)

`train.ipynb` 의 §1 에서 `USE_ROBOFLOW = True` 로 두면 외부 데이터셋을 자동으로 다운받아 위 구조로 병합한다. `ROBOFLOW_DATASETS` 리스트에 workspace/project/version 명시 필요.

## 8. 확인

데이터를 채운 뒤 `train.ipynb` 의 §3 셀을 실행하면 split 별 통계가 출력된다.

```
train: images=320, labels=320, classes={0:80, 1:80, 2:80, 3:80}  ✓ 균형
valid: images=40,  labels=40,  classes={0:10, 1:10, 2:10, 3:10}  ✓ 균형
test:  images=40,  labels=40,  classes={0:10, 1:10, 2:10, 3:10}  ✓ 균형
```
