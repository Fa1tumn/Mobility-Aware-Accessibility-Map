# 캠퍼스 격자 길찾기와 이동 편안함 지도

연세대학교 국제캠퍼스의 현장 관측, 출입구, IMU 편안함 점수를 한 지도에서 볼 수 있습니다. `config/campus_grid.json`의 고정 격자를 사용하며, 격자 한 변의 기본 목표 길이는 10m입니다.

## 지도를 다시 만들기

저장소 루트에서 실행합니다. 가상 환경의 Python에 `requirements-grid.txt`의 패키지를 설치하고, 현장 SQLite 파일을 `app/map/observations.sqlite3`에 둡니다. 이 파일은 실행할 때 읽기 전용으로 엽니다.

```powershell
.\.venv\Scripts\python.exe -m scripts.test_grid --sqlite app/map/observations.sqlite3 --field comfort_cost
.\.venv\Scripts\python.exe -m scripts.open_grid output/grid/grid.html
```

브라우저가 열리면 `Grid layer`에서 `Ride comfort`와 `Vibration frequency (Hz)`를 전환할 수 있습니다. 서버 명령을 실행한 터미널은 지도를 보는 동안 열어 두고, 종료할 때는 `Ctrl+C`를 누릅니다.

| 파일 | 내용 |
| --- | --- |
| `output/grid/grid.html` | 출입구와 경로를 포함한 대화형 지도 |
| `output/grid/grid.png` | 선택한 지표로 그린 정적 격자 지도 |
| `output/grid/grid.json` | 격자 좌표, 집계값, 해당 격자의 IMU 편안함 통계 |
| `output/grid/grid_observations.json` | 입력 관측 레코드 |

다른 출입구 자료는 `--entrances <GeoJSON>`, 다른 IMU 실험 자료는 `--comfort <GeoJSON>`으로 지정합니다.

## 출입구와 격자 길찾기

1. 지도 핀 또는 `Entrance navigation` 목록에서 출입구를 선택합니다. 장소로 등록된 핀은 정보만 표시합니다.
2. `Set start on map`으로 출발점을 찍거나 `Use my location`으로 현재 위치를 사용합니다. 출발점에 관측이 없으면 경계가 25m 이내인 가장 가까운 관측 격자에 연결합니다.
3. 출입구가 속한 격자에 관측이 있으면 그 격자가 목적지입니다. 비어 있으면 출입구에서 **격자 경계까지의 거리**가 가장 짧은 관측 격자를 사용합니다. 화면에서 실제 출입구 핀과 도착 격자를 함께 확인할 수 있습니다.
4. 변이나 꼭짓점을 맞댄 관측 격자의 중심을 이어 경로를 계산합니다. `Shortest`는 중심 사이의 거리 합을 최소화합니다. `Comfort first`는 이 거리에 격자에 집계된 노면 종류와 분류 신뢰도를 반영한 비용을 더합니다.

지도에 표시하는 거리는 격자 중심 사이의 거리입니다. 대각선으로 맞닿은 격자의 연결과 출입구까지의 마지막 구간은 현장 통행 가능성을 별도로 확인해야 합니다. 관측 격자 사이에 연결된 경로가 없으면 화면에 표시합니다.

## IMU 편안함 시각화

`data/campus/comfort.geojson`에는 [RUBIK Pi PR #7](https://github.com/Fa1tumn/Mobility-Aware-Accessibility-Map-rubik/pull/7)의 `block_comfort.geojson`에서 가져온 좌표, 편안함 비용, 수직 진동 RMS, 10m당 충격 수가 들어 있습니다. 원본 커밋과 파일의 SHA-256도 함께 기록했습니다.

PR은 2초 창별 수직 진동 RMS와 10m당 충격 수를 전체 실험의 기준값으로 나눈 뒤 두 항을 50%씩 반영합니다. 충격 항은 창의 값과 기준 중앙값에 각각 1을 더한 뒤 나눕니다. 지도는 같은 격자에 들어온 창별 비용의 **중앙값**을 표시합니다. 격자를 선택하면 수직 RMS와 10m당 충격 수의 중앙값, 사용한 창 수를 볼 수 있습니다.

| 편안함 비용 | 색 |
| --- | --- |
| 0.85 미만 | 진한 초록 |
| 0.85 이상 1.00 미만 | 연한 초록 |
| 1.00 이상 1.15 미만 | 노랑 |
| 1.15 이상 1.40 미만 | 주황 |
| 1.40 이상 | 빨강 |
| 비용을 계산할 수 있는 IMU 창 없음 | 회색 |

1.00은 해당 실험의 기준값입니다. 수치가 낮을수록 상대적으로 편한 것으로 추정하며, 비용의 가중치와 구간 경계는 실험용입니다. `Ride comfort`는 실측 IMU 비용을 보여 주고, `Comfort first`의 경로 계산에는 노면 분류 비용을 사용합니다.

## 2026-11-27 현장 자료 검증

- SQLite 관측 2,401건 중 2,400건을 격자에 배치했습니다. 관측이 있는 격자는 516개입니다.
- 실제 출입구 45곳 중 3곳은 관측 격자에 들어가고, 42곳은 가장 가까운 관측 격자를 목적지로 선택합니다. 장소 1곳도 지도에 표시합니다.
- IMU 창 2,219개 중 2,218개가 지도 범위 안에 있으며, 507개 격자에 비용이 표시됩니다. 이 중 501개 격자에 SQLite 관측도 있습니다.
- 자유관 A 출입구를 대상으로 한 브라우저 확인에서 `Shortest`는 G2917에서 G2802까지 관측 격자 21개를 지나는 약 236m 경로를 계산했습니다. 같은 화면에서 격자 선택, 결측 표시와 지표 전환도 확인했습니다.

```powershell
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe -m pytest tests/test_grid.py tests/test_grid_map.py tests/test_refresh_grid.py tests/test_open_grid.py -q
```
