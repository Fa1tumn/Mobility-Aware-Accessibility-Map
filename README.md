# Mobility-Aware Accessibility Map

교통약자의 이동 접근성을 위한 비전 인식 PoC 프로젝트입니다. 현재 프로젝트는 다음 모델을 사용합니다.

- YOLO: 차량, 보행자, 장애물과 향후 사용자 정의 학습을 통해 계단, 단차, 경사로 감지
- DeepLabV3+ (Cityscapes): 도로, 보도 등 영역 분할
- 향후 감지 결과, 분할 결과, GPS 정보를 결합하여 이동 방식별 통행 가능 여부 판단

현재 저장소는 초기 개발 단계입니다. DeepLabV3+ 추론 코드와 기본 YOLO 추론 코드는 실행할 수 있으며, 나머지 여러 모듈은 아직 구현 전의 기본 구조만 포함하고 있습니다.

## 프로젝트 구조

```text
Mobility-Aware-Accessibility-Map/
├── app/
│   ├── camera/
│   │   └── capture.py                 # 카메라 입력 인터페이스 기본 구조
│   ├── detection/
│   │   └── detector.py                # 공통 감지 인터페이스 기본 구조
│   ├── inference/
│   │   ├── deeplab_segmenter.py       # DeepLabV3+ Cityscapes 추론
│   │   ├── yolo_detector.py           # Ultralytics YOLO 추론 래퍼
│   │   ├── perception.py              # 인식 결과 융합 모듈 기본 구조
│   │   └── example_photo/
│   │       └── bus.jpg                # 추론 예제 이미지
│   ├── location/                      # GPS 및 시간 동기화 모듈 기본 구조
│   ├── map/                           # 지도 생성 모듈 기본 구조
│   ├── observation/                   # 관측 데이터 구조 모듈 기본 구조
│   ├── safety/                        # 통행 가능성 및 품질 판단 모듈 기본 구조
│   ├── storage/                       # 데이터베이스 저장 모듈 기본 구조
│   ├── config.py
│   └── main.py
├── data/
│   ├── captures/                      # 캡처 이미지 데이터
│   └── gps/                           # GPS 데이터
├── evidence/                          # 단계별 검증 자료
├── models/
│   ├── deeplab/
│   │   └── deeplabv3plus_r18-d8_512x1024_80k_cityscapes_20201226_080942-cff257fe.pth
│   └── yolo/
│       └── yolov8n.pt
├── output/
│   ├── deeplab/                       # DeepLab 마스크 및 시각화 결과
│   └── yolo_detection/                # YOLO 시각화 결과
├── scripts/                           # 도구 및 벤치마크 스크립트 기본 구조
├── tests/                             # 테스트 및 수동 검증 스크립트
├── config.yaml
├── requirements.txt
└── README.md
```

## 실행 환경

현재 의존성 조합은 다음 환경에서 검증되었습니다.

```text
WSL 2
Python 3.10
PyTorch 2.1.0 CPU
torchvision 0.16.0 CPU
MMCV 2.1.0
MMEngine 0.10.7
MMSegmentation 1.2.2
Ultralytics 8.4.161
```

현재 `requirements.txt`는 CPU용 PyTorch를 설치하도록 구성되어 있습니다. NVIDIA GPU를 사용하려면 그래픽 드라이버와 CUDA 버전에 맞는 PyTorch 및 MMCV wheel을 선택해야 합니다. 서로 다른 CUDA/PyTorch/MMCV 조합을 임의로 혼용하면 안 됩니다.

## Conda 환경 생성 및 설치

다음 명령은 WSL 터미널에서 실행합니다.


Python 3.10 환경을 생성합니다.

```bash
conda create -n mobility-map python=3.10 pip -y
```

환경을 활성화합니다.

```bash
conda activate mobility-map
```


프로젝트 의존성을 설치합니다.

```bash
python -m pip install -r requirements.txt
```

이후 WSL 터미널을 다시 열었을 때는 다음 명령만 실행하면 됩니다.

```bash
cd /mnt/e/Code/python/Mobility-Aware-Accessibility-Map
conda activate mobility-map
```

```bash
conda activate mobility-map
```

## DeepLabV3+ 실행

DeepLab 가중치는 다음 경로에 저장되어 있습니다.

```text
models/deeplab/deeplabv3plus_r18-d8_512x1024_80k_cityscapes_20201226_080942-cff257fe.pth
```

프로젝트 루트에서 다음 명령을 실행합니다.

```bash
python app/inference/deeplab_segmenter.py
```

예제 입력 이미지:

```text
app/inference/example_photo/bus.jpg
```

출력 파일:

```text
output/deeplab/vis/bus.jpg
output/deeplab/pred/00000000_pred.png
```

- `vis/bus.jpg`: 클래스 색상이 원본 이미지에 합성된 시맨틱 분할 시각화
- `pred/00000000_pred.png`: 각 픽셀 값이 클래스 ID를 나타내는 예측 마스크

Cityscapes 가중치는 도로, 보도, 보행자, 차량 등의 클래스를 구분할 수 있지만 계단, 단차, 일반 경사로는 직접 구분하지 못합니다. 이러한 클래스는 접근성 데이터셋으로 YOLO를 추가 학습하거나 해당 클래스를 포함한 분할 모델을 별도로 학습해야 합니다.

## YOLO 사용

YOLO 가중치는 다음 경로에 저장되어 있습니다.

```text
models/yolo/yolov8n.pt
```

현재 `YOLODetector`는 기본 추론 래퍼입니다. 일반 YOLO 가중치는 사람, 자동차, 자전거 등의 일반 객체를 감지할 수 있지만 계단, 단차, 경사로는 안정적으로 감지하지 못합니다. 해당 클래스는 접근성 환경 데이터로 추가 학습해야 합니다.

## 테스트

프로젝트 루트에서 pytest를 실행합니다.

```bash
python -m pytest
```

현재 일부 테스트 파일은 비어 있습니다. `tests/test_yolo_output.py`도 자동화된 단위 테스트보다는 수동 추론 스크립트에 가깝고, 아직 결과를 검증하는 `assert`가 없습니다. 각 모듈 구현이 진행되면 실제 `test_*` 테스트 함수를 추가해야 합니다.

## 인식 및 통행 가능성 판단 구조

계획 중인 처리 흐름은 다음과 같습니다.

```text
카메라 영상
├── DeepLabV3+: road / sidewalk 등 통행 후보 영역 분할
├── YOLO: 사람, 차량, 장애물, 단차, 계단, 경사로 감지
└── 판단 모듈: 사용자 이동 방식에 따라 결과 융합
    ├── 일반 보행자
    └── 휠체어 사용자
```

보도로 분류되었다고 해서 반드시 통행 가능한 것은 아닙니다. 최종 판단에서는 장애물, 단차, 계단을 제외해야 하며, 휠체어 통행 가능 여부를 판단하려면 경사도 또는 깊이 정보도 함께 고려해야 합니다.
