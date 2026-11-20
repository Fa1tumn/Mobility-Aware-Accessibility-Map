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
9월 데모 graph(`data/routing_demo`)의 휠체어 경로가 모두 막히므로 프리셋은 바꾸지 않았다.

11/19 실측에서는 실험 구역 경사로가 6% 안팎이었다(R1 +6.5%, 같은 경사로 왕복 평균 6.59%).
이 값이면 1/12를 써도 막히지 않는다. 경사로를 더 재고 팀이 정해서 설정으로 바꾼다.

```python
from app.profile.definitions import WHEELCHAIR, RAMP_LIMIT_PCT
strict = WHEELCHAIR.with_overrides(max_slope_pct=RAMP_LIMIT_PCT)
```

## 경로 결과 (scripts/route.py 출력)

`FeatureCollection` 하나. 피처 하나가 경로의 간선 하나이고, 전체 요약은
최상위 `properties`에 둔다.

| 위치 | 필드 |
|---|---|
| 최상위 `properties` | `profile`, `found`, `start`, `goal`, `when`, `node_path`, `total_distance_m`, `total_cost`, `unknown_slope_m`, `max_uphill_pct`, `max_downhill_pct`, `blocked`, `event_ids` |
| 피처 `properties` | `seq`, `edge_id`, `reverse`, `from_node`, `to_node`, `distance_m`, `slope_pct`(진행 방향 기준), `surface`, `stairs`, `cost`, `reasons`, `events` |

- `--events`로 이벤트 파일을 주면 `cost`에 이벤트 추가 비용이 들어가고, `reasons`와 `events`에
  `정차 차량·킥보드 E001 (10:30까지)` 같은 표기가 들어간다. 이벤트가 없으면 `events`·`event_ids`는 빈 목록이다.
- `scripts/event_demo.py --out-dir`의 단계별 파일은 최상위에 `action`(keep · reroute · no_route · arrived)과
  `decision_reasons`가 더 붙는다.
- 이벤트 형식과 규칙: [route-choice-and-events.md](route-choice-and-events.md)

```bash
python -m scripts.route --graph tests/fixtures/routing_mini.geojson \
    --from A --to D --profile all --out output/route/route.geojson
```

## 출입구 운영 시간 (schedule JSON)

간선의 `entrance_id`가 이 파일의 출입구 `id`를 가리킨다. 그 간선은 출입구가 열려 있을 때만 지날 수 있다.
예시: `tests/fixtures/schedule_buildings.json`(시험용), `data/campus/schedule.json`(언더우드기념도서관).

```json
{
  "periods": [
    {"id": "semester", "label": "학기 중", "from": "2026-09-01", "to": "2026-12-18", "verified": false},
    {"id": "vacation", "label": "방학 중", "from": "2026-12-19", "to": "2027-02-28", "verified": false}
  ],
  "holidays": ["2026-12-25"],
  "entrances": [
    {"id": "underwood_ground_stepfree", "name": "…", "building": "…",
     "hours": {"semester": {"weekdays": ["09:00-18:00"], "sunday": ["12:00-18:00"]}, "vacation": {}},
     "verified_at": "2026-11-20", "source": "…"}
  ]
}
```

| 규칙 | 내용 |
|---|---|
| 시간표 | 기간형(`{기간 ID: {요일: [구간]}}`) 또는 9월 요일형(`{요일: [구간]}`) |
| 요일 키 | `monday`~`sunday`, 묶음 `weekdays`·`weekend`·`daily`, 공휴일 `holiday`. 개별 요일이 묶음보다 우선 |
| 구간 | `"HH:MM-HH:MM"`, 끝 `24:00` 허용, 시작 > 끝이면 자정을 넘김. 끝 시각은 포함하지 않음 |
| 닫힘으로 보는 경우 | 시간표에 없는 요일, 어느 기간에도 속하지 않는 날짜, `holiday` 키 없는 공휴일, 등록되지 않은 출입구 |
| 기간 겹침 | `periods`에 먼저 적은 기간이 우선(시험기간을 학기보다 앞에) |
| `verified: false` | 학사일정으로 확인하지 않은 날짜. 사유 문구에 "(기간 미확인)"이 붙음 |

막힌 이유는 "출입 불가 — 도서관 지상 계단 없는 문: 학기 중 금요일 09:00-18:00 개방, 지금 19:00 닫힘"처럼 나온다.

## 건물 (buildings JSON)

출발·도착을 건물로 고를 때 쓴다. 건물 하나에 출입구 노드가 여러 개일 수 있다.
예시: `tests/fixtures/buildings_mini.json`.

```json
{"buildings": [
  {"id": "library", "name": "도서관", "entrances": ["L1", "L2", "L3"],
   "point": [126.67, 37.38], "outline": [[126.67, 37.38], …], "note": ""}
]}
```

- `entrances`는 graph의 노드 ID. 없는 노드, 두 건물에 겹친 출입구, 정의되지 않은 속성은 오류다.
- `point`가 없으면 출입구 좌표 평균을 쓴다. `outline`은 지도 표시용(선택).
- 운영 시간은 여기 적지 않는다. 출입구로 들어가는 간선의 `entrance_id`로 운영 시간 파일을 참조한다.
- 노드 ID `@origin`, `@dest`는 건물 간 탐색의 가상 노드로 예약되어 있다.

건물 간 경로는 출발 건물의 모든 출입구와 도착 건물의 모든 출입구 조합 중 비용이 가장 낮은 경로를
한 번의 탐색으로 고른다. 경사·운영 시간·이벤트 때문에 A→B와 B→A는 따로 계산한다.

```bash
python -m scripts.building_route --graph tests/fixtures/routing_buildings.geojson \
    --buildings tests/fixtures/buildings_mini.json --schedule tests/fixtures/schedule_buildings.json \
    --from student_hall --to library --profile wheelchair --when 2026-11-20T19:00
```

`--out` 파일은 위 경로 결과 형식에 `origin_building`, `dest_building`, `from_entrance`, `to_entrance`,
`why`, `entrance_notes`(쓸 수 없는 출입구와 이유)가 더 붙는다.
