# 경로 graph 데이터 형식

실험 구역 보행로 graph를 GeoJSON 한 파일로 둔다. `scripts/route.py --graph`와
`app.graph.loader.load_geojson()`이 이 형식을 읽는다. 예시는
`tests/fixtures/routing_mini.geojson`(시험용 합성 graph, 실제 캠퍼스 아님)이다.

## 단위와 방향

| 항목 | 규칙 |
|---|---|
| 좌표 | GeoJSON 순서 `[경도, 위도]` (WGS84) |
| 경사 | **`slope_pct`(%)** 가 기본. IMU의 `slope_percent`와 같은 단위. 각도는 엔진 내부 비교에서만 쓰고 `slope_deg`로 자동 계산된다 |
| 경사 부호 | 간선의 `from_node → to_node` 방향으로 오르막이면 `+`, 내리막이면 `-` |
| 역방향 | 간선 하나로 양방향을 모두 나타낸다. 반대로 지나갈 때 엔진이 경사 부호와 선 좌표를 뒤집는다 |
| 미측정 | 값을 비워 둔다(`null` 또는 생략). 0은 "평지"라는 뜻이므로 모를 때 0을 넣지 않는다 |
| 거리 | `distance_m`을 생략하면 선 좌표로 계산한다 |

## 노드 (Point 피처)

노드는 속성이 바뀌는 지점에 둔다: 분기점, 경사 시작·끝, 건물 출입구, 계단 끝.

| 속성 | 필수 | 설명 |
|---|---|---|
| `id` | O | 고유 ID (예: `N1`) |
| `name` |  | 사람이 읽는 이름 |
| `kind` |  | `junction` / `entrance` / `destination` / `stair_end` |
| `level` |  | 층. 지상 0, 지하 -1 |

## 간선 (LineString 피처)

선 좌표는 `from_node` 위치에서 시작해 `to_node` 위치에서 끝나야 한다. 끝점이
노드에서 5m 넘게 떨어지면 읽을 때 오류를 낸다.

| 속성 | 필수 | 설명 |
|---|---|---|
| `id`, `from_node`, `to_node` | O | 간선 ID와 양 끝 노드 |
| `slope_pct` |  | 대표 경사(%). 부호는 from→to 기준 |
| `stairs` |  | 계단 단수. 0이면 없음 |
| `ramp` |  | 경사로 시설 여부 |
| `threshold_cm` |  | 문턱 높이 |
| `surface` |  | `unknown`, `asphalt`, `block`, `tile`, `concrete`, `tactile`, `damaged` |
| `width_level` |  | `unknown`, `narrow`, `normal`, `wide` |
| `env` |  | `outdoor`, `indoor`, `underground` |
| `entrance_id` |  | 출입구 개방 시간(schedule) 참조 키 |
| `source` |  | 값의 출처: `survey`, `gps`, `camera`, `official`, `unknown` |
| `confidence` |  | 0~1. 관측 횟수·품질 기반 신뢰도 |
| `verified_at`, `note` |  | 확인 날짜, 메모 |

정의되지 않은 속성이 있으면 오타를 막기 위해 읽을 때 오류를 낸다.

## 프로필 경사 한도

| 값 | 의미 |
|---|---|
| `RAMP_LIMIT_PCT = 8.33` | 경사로 기울기 1/12. 법규 참고값 |
| 휠체어 프리셋 `max_slope_deg = 8.0` | 9월 값 그대로. **약 14.1%로 1/12보다 느슨하다** |

9월 답사에서 캠퍼스 경사로가 약 -6°(약 10.5%)로 기록됐다. 1/12를 그대로 적용하면
데모 graph의 휠체어 경로가 모두 막히므로 프리셋은 바꾸지 않았다. 실측 후 팀이
정해서 설정으로 바꾼다.

```python
from app.profile.definitions import WHEELCHAIR, RAMP_LIMIT_PCT
strict = WHEELCHAIR.with_overrides(max_slope_pct=RAMP_LIMIT_PCT)
```

## 경로 결과 (scripts/route.py 출력)

`FeatureCollection` 하나. 피처 하나가 경로의 간선 하나이고, 전체 요약은
최상위 `properties`에 둔다.

| 위치 | 필드 |
|---|---|
| 최상위 `properties` | `profile`, `found`, `start`, `goal`, `when`, `node_path`, `total_distance_m`, `total_cost`, `unknown_slope_m`, `max_uphill_pct`, `max_downhill_pct`, `blocked` |
| 피처 `properties` | `seq`, `edge_id`, `reverse`, `from_node`, `to_node`, `distance_m`, `slope_pct`(진행 방향 기준), `surface`, `stairs`, `cost`, `reasons` |

```bash
python -m scripts.route --graph tests/fixtures/routing_mini.geojson \
    --from A --to D --profile all --out output/route/route.geojson
```
