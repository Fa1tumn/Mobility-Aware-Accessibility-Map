# Mobility-Aware Accessibility Map

## Roboflow 모델로 동영상 추론

`accesibility-street/11` 모델을 Roboflow Serverless API로 호출하여 `yolov11/example.mp4`의 모든 프레임을 처리합니다.
영상 프레임은 Roboflow 서비스로 전송되며, API key는 요청 헤더로 전달합니다.
동영상 파일은 용량이 크므로 Git 추적에서 제외합니다. 입력 영상은 로컬의 `yolov11/example.mp4`에 별도로 배치하세요.

```powershell
python -m pip install -r requirements-roboflow.txt
```

`.env`의 `ROBOFLOW_API_KEY`에 key를 입력한 후 프로젝트 루트에서 실행합니다.

```powershell
python -m yolov11.roboflow_video --workers 8
```

기본 출력 영상은 `yolov11/roboflow_output.mp4`입니다. 원본 영상과 기존 `yolov11/output.mp4`는 입력 또는 출력 대상으로 덮어쓰지 않습니다.
원본 해상도와 프레임 속도를 유지하고 H.264 MP4로 저장하며, 원본에 오디오가 있으면 함께 포함합니다.
API에 전송할 프레임은 긴 변이 최대 960픽셀이 되도록 축소하고, 반환된 검출 좌표는 원본 해상도로 환산합니다.
기본 신뢰도 임계값은 0.25이며, `--confidence`로 변경할 수 있습니다.

검출 결과는 `output/roboflow/accesibility-street-v11/predictions.jsonl`에 프레임별로 저장됩니다.
같은 입력과 설정으로 명령을 다시 실행하면 저장된 프레임은 재요청하지 않습니다.
모델, 입력 파일, 임계값 또는 전송 크기가 달라지면 별도의 `--cache-dir`를 지정해야 합니다.
추론이 완료된 캐시로 영상만 다시 생성하려면 다음 명령을 사용합니다.

```powershell
python -m yolov11.roboflow_video --render-only
```

짧은 실제 API 연결 테스트는 다음과 같이 실행합니다.

```powershell
python -m yolov11.roboflow_video --limit 3 --output output/roboflow/smoke.mp4
```

같은 캐시 폴더에 `summary.json`, `metadata.json`, 검출 결과를 그린 `preview_*.jpg`, 인코딩 로그를 저장합니다.
`summary.json`의 클래스별 개수는 프레임마다 검출된 결과의 합계이며, 서로 다른 실제 물체의 수를 의미하지 않습니다.
영상에는 영어 라벨을 사용하며, JSON에는 모델이 반환한 원래 클래스 이름도 보존합니다.
`necesita rampa`, `dificulta el paso`, `suelo inestable`는 각각 `Ramp needed`, `Passage obstructed`, `Unstable ground`로 표시합니다.
`inaccesible por obras`는 `Construction blockage`, `rampa inaccesible`는 `Inaccessible ramp`로 표시합니다.
추론 코드는 `yolov11/roboflow_video.py`이며, 기존 로컬 YOLO 스크립트 `yolov11/test.py`는 그대로 사용할 수 있습니다.

## Supabase 데이터 및 Grid 시각화

프로젝트 루트에서 실행합니다. 이 기능은 다음 의존성만 필요하며, 비전 모델을 설치할 필요는 없습니다.

```powershell
python -m pip install -r requirements-grid.txt
```

`.env`에 `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_TABLE`을 입력합니다.
URL에는 `https://your-project.supabase.co`와 같은 프로젝트 주소를 사용합니다. `/rest/v1/`로 끝나는 REST 주소도 지원합니다. KEY는 publishable key와 기존 anon JWT key를 지원합니다.
테이블의 SELECT 정책에서 사용자 로그인을 요구하는 경우, 해당 사용자의 액세스 토큰을 `SUPABASE_ACCESS_TOKEN`에 입력합니다.
데이터 조회에는 현재 key와 사용자의 데이터베이스 권한이 적용됩니다. 조회 결과가 빈 목록이면 SELECT 정책에 의해 데이터가 숨겨졌을 수도 있습니다.
`.env`는 Git 추적 대상에서 제외되며, `.env.example`은 저장소에 포함할 수 있는 빈 설정 템플릿입니다.

기본 테이블 이름은 `observations`이며, `app/map/test_observations.sqlite3`의 실제 구조에 맞춰 연결되어 있습니다.

| 필드 | 자료형 및 용도 |
| --- | --- |
| `id` | 고유 번호. 페이지 단위 조회 시 정렬 기준으로 사용 |
| `latitude`, `longitude` | 필수 위도 및 경도 값 |
| `record_time` | ISO 형식의 시간 문자열. 예: `2026-10-16T00:00:00Z` |
| `surface_label` | 노면 종류 문자열. NULL 허용 |
| `surface_confidence` | 0~1 범위의 신뢰도. NULL 허용 |
| `slope_percent` | 부호를 유지하는 경사도 백분율. grid의 `ramp`로 변환 |
| `vibration_frequency_avg_hz` | 평균 진동 주파수(Hz). grid의 `ave_vibration`으로 변환 |
| `objects_supported` | 0이면 장애물 인식 미지원이며, 장애물 지표는 미확인 상태로 유지 |
| `objects` | 장애물 인식을 지원할 때 JSON 배열로 읽고, 배열 길이를 grid의 `object`로 사용 |

`ramp`, `ave_vibration`, `object` 필드를 직접 사용하는 레코드도 지원하며, 해당 필드가 있으면 우선 사용합니다.
`objects_supported=1`이고 `objects=[]`일 때 장애물 수를 0으로 변환합니다. `objects=null`은 미확인 상태로 유지합니다.
제공된 원본 샘플의 `objects`는 모두 비어 있으므로, 비어 있지 않은 배열의 처리는 모의 테스트로 검증했습니다. 실제 수집 장치의 장애물 출력 형식과 추가로 대조해야 합니다.

`SUPABASE_ORDER`의 기본값은 `record_time.asc,id.asc`입니다. `id`가 없다면 실제 고유 키로 변경해야 하며, 정렬에 사용되는 필드는 테이블에 존재해야 합니다.
Supabase REST API를 통해 정렬 순서대로 한 번에 최대 1,000개씩 요청하고, 빈 페이지가 반환될 때까지 조회합니다.
페이지 단위로 조회하는 동안에는 데이터가 변경되지 않는 조건을 권장합니다. 동시에 레코드가 추가되거나 삭제되면 offset 방식으로 동일 시점의 전체 스냅샷을 보장할 수 없습니다.

데이터베이스 설정 없이 모의 데이터로 시각화를 확인할 수 있습니다.

```powershell
python -m scripts.test_grid --demo --output output/grid/demo.png
```

각 격자는 하나의 영역에 대응합니다. 왼쪽 그림은 영역 ID를, 오른쪽 그림은 해당 영역의 집계값을 표시합니다. 같은 격자에 속한 여러 관측값은 하나의 영역 가중치로 집계됩니다.
PNG, JSON, 지도 배경이 포함된 HTML을 함께 생성합니다. HTML을 열면 지도를 확대하거나 영역을 클릭하여 집계값과 관측 수를 확인할 수 있습니다.
HTML은 Leaflet과 OpenStreetMap을 사용하며, 지도 구성 요소와 배경 지도를 불러올 때 인터넷 연결이 필요합니다. PNG는 오프라인에서도 확인할 수 있습니다.
HTML 파일을 더블 클릭하지 말고 아래의 로컬 웹 서버 명령으로 여세요. `file://`로 열면 배경 지도 요청에 출처 정보가 없어 OpenStreetMap에서 403으로 차단할 수 있습니다. [지도 서비스 정책](https://operations.osmfoundation.org/policies/tiles/)에 따라 HTTP 주소로 열도록 구성했습니다.
웹페이지와 시각화의 인터페이스 언어는 영어이며, 이 README의 설명은 한국어로 제공합니다.

연세대학교 국제캠퍼스(송도) 모의 테스트는 다음 명령으로 실행합니다.

```powershell
python -m scripts.test_grid --yonsei-demo
```

`output/grid/yonsei_demo.html`, `yonsei_demo.png`, `yonsei_demo.json`, `yonsei_demo_observations.json`을 생성합니다.

생성한 지도를 브라우저에서 열려면 프로젝트 루트에서 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m scripts.open_grid
```

`http://127.0.0.1:8765/yonsei_demo.html`을 자동으로 엽니다. 사용하는 동안 터미널을 열어 두고, 종료할 때 `Ctrl+C`를 누르세요.
이 서버는 지정한 HTML 하나만 제공하며 프로젝트의 `.env`나 다른 파일은 제공하지 않습니다. 포트를 이미 사용 중이면 `--port 8766`을 추가합니다.
다른 결과 파일은 `python -m scripts.open_grid output/grid/regions.html`처럼 지정할 수 있습니다.
파일을 직접 열면 배경 지도는 비활성화되며 격자와 관측점 데이터는 계속 표시됩니다. HTTP 페이지에서 배경 지도 요청이 실패하면 해당 배경을 자동으로 숨깁니다.
HTTP 주소에서도 차단된다면 네트워크 또는 지도 서비스의 추가 제한일 수 있습니다. `Basemap`을 끄면 격자와 오른쪽 데이터를 확인할 수 있습니다.

캠퍼스 주소는 [연세대학교 공식 안내](https://www.yonsei.ac.kr/en_sc/1835/subview.do)에서 확인했습니다. 지도 기준점은 대략 위도 37.38165, 경도 126.67320이며, [지도 위치](https://mapcarta.com/W314908138)를 참고했습니다.
시연 범위는 북쪽 37.385, 남쪽 37.378, 서쪽 126.668, 동쪽 126.677로 설정했으며, 캠퍼스의 공식 경계를 의미하지 않습니다.
모의 관측점은 24개이며, 기본 설정에서 12개 영역에 각 2개의 레코드가 배치됩니다. 위치와 측정값은 모두 모의 데이터로, 실제 도로나 실측 통행 조건을 나타내지 않습니다.

HTML 오른쪽에는 모든 관측점의 위도·경도, 기록 시간, 노면 종류와 신뢰도, 경사도, 진동 주파수, 장애물 수, 개별 관측점의 시험 계산 가중치, 영역 집계 가중치를 표시합니다. 전체 레코드를 펼쳐 볼 수도 있습니다.
각 관측점에는 P01, P02 등의 번호를, 각 영역에는 G와 격자 번호를 조합한 ID를 사용합니다. 오른쪽 목록이나 지도에서 관측점을 클릭하면 해당 영역을 강조하고, 관측점 상세 정보를 열며, 목록의 해당 레코드로 이동합니다.
같은 영역에 속한 관측점도 각각의 원본 측정값을 유지하며, 영역 블록에는 하나의 집계값을 표시합니다.
Supabase, SQLite, JSON 입력에도 동일한 오른쪽 관측점 목록을 적용합니다.

현재 Supabase 데이터를 더 큰 영역 블록으로 표시하려면 다음 명령을 사용합니다.

```powershell
python -m scripts.test_grid --size 0.002 --field ave_vibration --output output/grid/regions.png
```

`--size`는 이번 실행에서 사용할 `GRID_SIZE`를 지정하며, 단위는 도(degree)입니다. 제공된 5개 샘플은 좌표 간 거리가 커서 `0.0001`을 사용하면 2만 개 이상의 작은 격자가 생성됩니다. `0.002`를 사용하면 영역을 더 쉽게 구분할 수 있습니다.
이후 실행에도 같은 크기를 사용하려면 `.env`의 `GRID_SIZE`를 변경합니다.
`grid_id`는 북쪽에서 남쪽으로, 각 행에서는 서쪽에서 동쪽으로 부여합니다. JSON에는 ID, 영역의 위도·경도 경계, 가중치, 관측 수가 포함됩니다.
격자 크기와 경계가 같으면 영역 번호도 유지됩니다. 장기간 같은 번호를 사용하려면 `.env`의 네 경계값을 고정하여 입력 데이터에 따라 자동 범위가 바뀌지 않도록 설정합니다.

제공된 SQLite 데이터베이스를 읽기 전용으로 열어 경사도 또는 진동 주파수를 확인할 수 있습니다.

```powershell
python -m scripts.test_grid --sqlite app/map/test_observations.sqlite3 --field ramp --output output/grid/database_slope.png
python -m scripts.test_grid --sqlite app/map/test_observations.sqlite3 --field ave_vibration --output output/grid/database_vibration.png
```

`--field`에는 `weight`, `ramp`, `ave_vibration`, `object`를 지정할 수 있으며, 기본값은 `weight`입니다.
제공된 원본 샘플 5개는 모두 `objects_supported=0`이므로 경사도와 진동은 표시할 수 있지만, 종합 가중치는 미확인 상태입니다.
관측값이 있는 격자는 영역 전체를 채색하고, 관측값이 없는 영역은 흰색으로 표시합니다. 정적 그림은 행과 열이 각각 25개 이하일 때 번호와 수치를 표시합니다. 더 촘촘한 격자는 HTML에서 확대하여 확인할 수 있습니다.

설정을 입력한 후 Supabase에서 직접 읽어 이미지와 격자별 JSON을 생성합니다.

```powershell
python -m scripts.test_grid
```

`--field ramp` 또는 `--field ave_vibration`을 추가하면 개별 지표를 확인할 수 있습니다.

데이터 조회와 시각화를 나누어 실행할 수도 있습니다.

```powershell
python -m scripts.fetch_supabase
python -m scripts.test_grid --input data/observations.json
```

기본 결과 파일은 `output/grid/grid.png`, `output/grid/grid.json`, `output/grid/grid.html`입니다.
실행할 때마다 현재 데이터를 읽고 격자를 다시 구성합니다. 데이터를 갱신하려면 명령을 다시 실행합니다.
`--demo`는 별도의 모의 좌표와 고정 경계를 사용하며, `.env`에 지정된 지도 경계의 영향을 받지 않습니다.

`app/map/gird.py`는 기존 파일명과 `grid` 클래스를 유지합니다. 좌표 순서는 `(위도, 경도)`이며, 왼쪽 위는 북쪽/서쪽, 오른쪽 아래는 남쪽/동쪽에 해당합니다.
`GRID_SIZE`의 단위는 위도·경도의 도(degree)이며 기본값은 `0.0001`입니다. 미터 단위가 아닙니다. 네 경계값을 모두 비워 두면 관측 범위에 따라 자동으로 설정하며, 모두 입력하면 지도 범위를 고정합니다. 수동으로 설정한 범위를 벗어난 관측점은 오류로 처리합니다.
영역 끝에 격자 크기보다 작은 구간이 남으면 올림하여 포함합니다. 행 번호는 남쪽으로, 열 번호는 동쪽으로 증가합니다.

같은 격자의 경사도와 진동은 유효 표본의 산술평균을 사용합니다. 노면 종류는 신뢰도가 가장 높은 결과를, 장애물 값은 시간순으로 가장 최근의 유효 레코드를 사용합니다.
`insert_grid_observation(observation)`은 필드 딕셔너리 하나를 받아 내부 `self.grid`를 갱신합니다. 별도의 grid 인자는 전달하지 않습니다.
가중치는 `0.3 * ramp + 0.3 * ave_vibration + 0.3 * object + 0.1`로 계산합니다.
이 식은 프로토타입용이며, 서로 다른 지표의 정규화를 아직 적용하지 않았습니다. 검증된 휠체어 통행 가능성 판단값으로 바로 사용할 수는 없습니다.
세 지표 중 누락값이 남아 있으면 가중치는 `None`으로 유지하며, 화면에서는 회색 또는 `N/A`로 표시합니다.
색상이 붉을수록 현재 지표의 수치가 높습니다. 경사도 그림은 방향을 나타내는 부호를 유지하므로, 붉은색이 곧 더 위험하다는 뜻은 아닙니다.
PNG는 영역별 격자 그림이며, HTML은 같은 영역을 지도 위에 겹쳐 표시합니다. 번호와 수치는 JSON 결과와 일치합니다.

추가 코드는 일반 함수, 반복문, 딕셔너리, 클래스로 구성되어 있으며 코드 주석은 포함하지 않습니다. 테스트 명령은 다음과 같습니다.

```powershell
python -m pip install pytest
python -m pytest tests/test_grid.py tests/test_grid_map.py tests/test_supabase_reader.py -q
```

처리 순서는 `supabase_reader.py → grid_pipeline.py → gird.py → grid_visualization.py`입니다.

캠퍼스의 물리적 이동환경과 시간에 따라 변하는 출입 가능 정보를 통합하여, 사용자의 mobility profile과 현재 시각에 따라 이용 가능한 경로를 제공하는 Edge-assisted Mobility-Aware Routing PoC

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
