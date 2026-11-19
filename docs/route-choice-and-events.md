# 경로 선택 · 동적 이벤트 · 재탐색

[navigation-architecture.md](navigation-architecture.md)의 L6(경로 선택), L4(동적 이벤트 중
수동 입력), L7(재탐색 판단)을 구현한 내용과 확정한 규칙이다.

실제 graph와 간선 경사값(L2·L3)은 별도 작업이다. 여기 코드는 graph 파일만 있으면 동작하고,
개발·테스트는 합성 graph `tests/fixtures/routing_mini.geojson`으로 한다.

```text
A ──AB 0%, 40m── B
│                │ BD +15%, 30m (B→D 오르막)
AE +3%, 60m      D
│                │ CD -2%, 30m
E ──EC 미측정, 40m── C
```

## 1. 경로 선택 (L6)

| 파일 | 역할 |
|---|---|
| `app/routing/alternatives.py` | `route_options()`: 추천·최단·대안 경로 |
| `app/routing/explain.py` | `explain()`: 두 경로 차이를 문장으로 |
| `app/routing/metrics.py` | `route_metrics()`: 거리, 최대 오르막·내리막, 미측정 거리, 계단, 가파른 구간, 이벤트 |
| `app/routing/evaluate.py` | `evaluate_path()`: 이미 정해진 경로를 지금 조건으로 다시 판정 |

**규칙**

| 선택지 | 만드는 방법 |
|---|---|
| 추천 | 프로필 비용이 가장 낮은 경로 |
| 최단 | 제약을 모두 끄고 거리만 본 경로. 프로필로 못 가면 막힌 이유를 함께 준다. 추천과 같으면 따로 만들지 않고 추천에 "최단" 표시 |
| 대안 | 지금까지 나온 경로의 간선 비용을 1.5배로 올리고 다시 탐색. 최대 3개 |

대안은 아래 경우 버린다.

- 실제 비용(배율 뺀 값)이 추천보다 30% 넘게 비쌈
- 이미 있는 선택지와 80% 넘게 겹침(겹친 간선 거리 ÷ 짧은 경로 거리, 방향 무관)

**선택 이유**는 비용 값이 아니라 요약값 차이로만 쓴다. 추천은 최단과, 나머지는 추천과 비교한다.

| 항목 | 문장 | 기준 |
|---|---|---|
| 거리 | `60m 더 걸음` / `60m 더 짧음` | 5m 이상 차이 |
| 가파른 구간 | `오르막 15.0% 1곳 회피` / `내리막 6.5% 1곳 지남` | 5% 이상 구간, 진행 방향 기준 |
| 계단 | `계단 22단 회피` | |
| 경사 미측정 | `경사 미측정 40m 포함` / `… 적음` | 5m 이상 차이 |
| 이벤트 | `공사·통제 구간 회피 (E001)` | 경로 위 활성 이벤트 |

```text
$ python -m scripts.route --graph tests/fixtures/routing_mini.geojson --from A --to D \
      --profile wheelchair --explain
[wheelchair] 추천       A → E → C → D  130m  비용 1.46
    · 60m 더 걸음 · 오르막 15.0% 1곳 회피 · 경사 미측정 40m 포함
[wheelchair] 최단       A → B → D  70m  통행 불가
    · B→D: 오르막 경사 15.0% > 허용 14.1%
```

## 2. 동적 이벤트 (L4, 수동 입력)

| 파일 | 역할 |
|---|---|
| `config/events.json` | 종류별 유효시간, 막는 프로필, 프로필별 추가 비용 |
| `app/events/model.py` | `EventType`, `Event`, 상태 계산 |
| `app/events/store.py` | `EventStore`: 추가·해제·저장 (`data/events/events.json`) |
| `app/events/overlay.py` | `EventOverlay`: 특정 시각의 활성 이벤트를 간선별 효과로 |

### 종류 (`config/events.json`)

| 종류 | 이름 | 유효시간 | 막는 프로필 | 추가 비용 |
|---|---|---|---|---|
| `construction` | 공사·통제 | 직접 지정(없으면 해제할 때까지) | 전부 | - |
| `barricade` | 임시 설치물 | 1일 | wheelchair, luggage | 나머지 0.5 |
| `parked_vehicle` | 정차 차량·킥보드 | 30분 | - | wheelchair 2.0, luggage 0.5, 나머지 0 |
| `crowd` | 혼잡 | 10분 | 기록만, 경로 반영 안 함 | - |

- 추가 비용은 간선을 지날 때 한 번 더한다. 평지 100m가 1.0이므로 2.0은 "평지 200m를 더 걷는 만큼"이다.
- `"*"`는 "나머지 모든 프로필"이다. 프로필 이름이 따로 있으면 그 값을 쓴다.
- 숫자는 데모용 시작값이다. 프로필 한도처럼 팀이 정할 값이며 이 파일만 바꾸면 된다.

### 이벤트

| 필드 | 뜻 |
|---|---|
| `event_id` | `E001`부터 순서대로 |
| `type` | 위 종류 |
| `edge_id` | graph의 간선 ID. 역방향(`:rev`)이 아니라 원래 ID. **양방향에 적용** |
| `created_at`, `expires_at` | 한국 시간, 시간대 없는 ISO. `expires_at`이 없으면 해제할 때까지 |
| `status` | `active` · `cleared` (카메라용 `candidate` · `confirmed`는 자리만) |
| `source`, `note`, `cleared_at` | 출처(`manual`), 메모, 해제 시각 |
| `offset_from_m`, `offset_to_m`, `confidence`, `evidence` | 카메라 이벤트용. 저장만 하고 아직 쓰지 않음 |

**종료 시각**은 `until` > `minutes` > 종류 기본 유효시간 순으로 정한다.

**상태**는 저장하지 않고 시각으로 계산한다.
`pending`(만들기 전) → `active` → `expired`(`expires_at` 지남) 또는 `cleared`(해제).
경로에는 `active`만 반영한다.

### 경로에 반영

`feasibility.py`·`cost.py`는 그대로 두고, 탐색(`find_route(..., events=)`)과
재평가(`evaluate_path(..., events=)`)에서 효과를 더한다.

| 효과 | 탐색에서 |
|---|---|
| 차단 | 그 간선을 확장하지 않고 `blocked`에 사유: `B→D: 공사·통제 E001 (11:00까지)` |
| 비용 | 간선 비용에 더하고 경로 사유에 남김 |

경로 GeoJSON에는 간선마다 `events`, 최상위에 `event_ids`가 들어간다
([routing-data-contract.md](routing-data-contract.md)).

## 3. 재탐색 판단 (L7 일부)

`app/nav/reroute.py`의 `check_reroute(route, current_node, graph, profile, events, when)`.

| 순서 | 조건 | 결과 |
|---|---|---|
| 1 | 현재 위치가 도착 노드 | `arrived` |
| 2 | 현재 위치가 경로 위에 없음 | 그 위치에서 다시 찾음 → `reroute` (`경로 이탈: …`) |
| 3 | 남은 구간이 막힘(프로필 한도, 출입 시간, 차단 이벤트) | 다시 찾음 → `reroute`, 길이 없으면 `no_route` |
| 4 | 새 경로 비용 < 남은 경로 비용 × 0.9 | `reroute` (`새 경로가 비용 13% 낮음`) |
| 5 | 그 외 | `keep`. 남은 구간의 비용 이벤트는 주의 문구로 |

- 10% 기준(`HYSTERESIS`)은 경로가 왔다 갔다 하지 않게 하려는 값이다. 이벤트가 만료돼
  원래 길이 다시 좋아지는 경우도 4번으로 잡힌다.
- 이미 지나온 구간의 이벤트는 보지 않는다.
- 호출하는 쪽이 정할 것: 부르는 주기(설계값 30초, 이벤트가 바뀔 때도), GPS를 경로 위
  노드로 맞추기(위치 추적). 경로 이탈 거리 기준(max(15m, GPS 정확도×2) 2회 연속)도 위치 추적 쪽 몫이다.

```text
$ python -m scripts.event_demo data/events/demo_mini.json
10:00:00  [A] 출발: A → B → D (70m)
10:00:20  [A] 이벤트 추가: 공사·통제 E001 (10:01까지) @ BD
10:00:20  [A] 재탐색: A → E → C → D (130m)
          · 앞 구간 B→D: 공사·통제 E001 (10:01까지)
10:00:50  [A] 유지: A → E → C → D (130m)
10:01:10  [A] 재탐색: A → B → D (70m)
          · 새 경로가 비용 46% 낮음
10:01:40  [B] 이벤트 추가: 정차 차량·킥보드 E002 (10:31까지) @ BD
10:01:40  [B] 유지: B → D (30m)
10:02:10  [D] 도착
```

`--profile luggage`로 돌리면 B 단계에서 정차 차량이 주의 문구로 나온다(캐리어는 추가 비용 0.5).
시나리오의 위치는 일반 프로필 경로에 맞춰 적었으므로, 다른 프로필로 돌리면 경로 이탈 처리도 볼 수 있다.
`--out-dir`을 주면 단계마다 경로 GeoJSON(`step_NN.geojson`, `action`·`decision_reasons` 포함)을
저장한다. 웹 화면에서 순서대로 그리면 재탐색 데모가 된다.

## 4. 명령줄

```bash
python -m scripts.events types
python -m scripts.events add --type construction --edge BD --until 2026-11-21T18:00 \
    --graph data/graph/test_area.geojson --note "보수 공사"
python -m scripts.events add --type parked_vehicle --edge EC      # 기본 유효시간 30분
python -m scripts.events list            # 활성만 (--all: 만료·해제 포함)
python -m scripts.events clear E001

python -m scripts.route --graph data/graph/test_area.geojson --from N1 --to N6 \
    --profile wheelchair --events data/events/events.json --explain
python -m scripts.event_demo data/events/demo_mini.json --out-dir output/route/demo
```

시각을 바꿔 시연하려면 `scripts.events --now`, `scripts.route --when`을 쓴다.
`data/events/events.json`은 실행 중에 바뀌는 파일이라 git에 올리지 않는다.

## 5. 실제 graph와 맞출 것

실험 구역 graph(`data/graph/test_area.geojson`)를 만들 때 지킬 것.

1. **간선 ID 유지:** 이벤트는 간선 ID에 붙는다. 경사 구간을 나누며 graph를 다시 만들 때,
   바뀌지 않은 간선은 ID를 그대로 둔다. 나눈 간선은 새 ID를 쓰고, 그 간선에 걸린 이벤트는 다시 입력한다.
2. **두 갈래 이상:** 데모 출발·도착 사이에 경로가 둘 이상 있어야 대안과 재탐색이 보인다.
   11/19에 돈 한 바퀴 경로(경사 R1·R2 포함)는 시계·반시계 두 갈래라 조건을 만족한다.
3. **이벤트 확인:** graph를 바꾼 뒤 `scripts.events add --graph`로 새 이벤트의 간선 ID를
   확인한다. 이미 저장된 이벤트는 `list`로 보고 없는 간선이면 해제한다.

## 6. 아직 안 한 것

| 항목 | 메모 |
|---|---|
| A* | 다익스트라로 결과가 같아 미룸. 휴리스틱은 직선거리/100 × w_distance |
| 간선 일부(offset) 이벤트 | 지금은 간선 전체에 적용 |
| 카메라 이벤트 | 후보 → 확인 규칙, 객체 위치 추정, 부재 관측 |
| 위치 추적·안내 문구 | `app/nav/tracker.py`, `maneuvers.py` |
| 시간 의존 탐색 | 출입구 개방을 도착 예상 시각으로 판단 |
| 이벤트 비용 값 | 데모용 시작값. 팀 결정 필요 |
