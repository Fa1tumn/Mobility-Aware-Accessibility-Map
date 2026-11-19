# 경로 엔진 (9월 PoC 생존선 모듈 이식)

> 9월 PoC에서 만든 `maam_survival_modules`를 이 저장소의 `app/graph`, `app/profile`,
> `app/routing`, `app/schedule`로 옮겼다. 데모 데이터는 `data/routing_demo/`에 있다.

이동수단별로 서로 다른 통행 비용을 계산하는 Accessibility Routing 엔진.
물리 속성은 Edge 센싱과 현장 실측으로 수집하고, 시간 제약은 규칙으로 주입하며,
사용자 프로파일에 따라 경로를 다르게 산출한다.

**하드웨어와 센싱에 의존하지 않는다.** 카메라·GPS가 없어도 그대로 동작한다.

## 실행

    python -m pytest tests/test_routing_requirements.py -v   # 43 passed. 테스트 이름 = 검증한 요구사항
    python -m scripts.demo_route                              # Hero 데모

## 설계 원칙

> Edge는 환경을 관측하고, Server는 사용자의 프로파일에 따라 그 환경을 해석한다.

프레임 단위에서 "휠체어에게 어려움"을 판단하지 않는다. 그렇게 하면 프로파일이
추가될 때마다 인식 파이프라인을 다시 손대야 한다. 인식은 물리 속성만 내보내고,
해석은 이 모듈이 맡는다.

## 모듈

    app/graph/schema.py       Node / Edge / Graph 데이터 계약
    app/graph/loader.py       JSON 입출력
    app/profile/definitions.py  프로파일 3종 + 노면 페널티 표
    app/profile/feasibility.py  hard constraint -> 통행 가능/불가 + 사유
    app/profile/cost.py         soft preference -> 부담 비용
    app/profile/verdict.py      지도 표시용 3단계 등급 (라우팅은 거치지 않음)
    app/schedule/resolver.py  출입구 개방 시간
    app/routing/dijkstra.py   프로파일 인지 최단경로
    app/routing/compare.py    프로파일별 비교표 (Hero 화면)

## 데이터 계약

단위를 필드명에 넣는다. `distance_m`, `slope_deg`, `threshold_cm`.
`slope_deg`는 진행 방향 오르막이 +, 내리막이 -. 역방향 통행 시 부호가 뒤집힌다.

**미측정(`None`)은 "평평하다"가 아니라 "모른다"이다.** 0으로 처리하면 측정하지
않은 구간이 가장 싸 보여서 라우팅이 미측정 구간을 선호하게 된다. 그래서 보수적
기본값을 쓴다(`cost.UNKNOWN_SLOPE_PROXY_DEG`). 이번 데모 프로파일은 `w_slope=0`
이라 이 항이 꺼져 있지만, 나중에 켜더라도 버그가 생기지 않도록 로직을 맞춰 뒀다.

**Edge는 의미 단위 구간이다.** 노드는 분기점·출입구·계단 끝처럼 속성이 바뀌는
지점에 둔다. `trajectory`의 20m 분석 윈도우와는 다른 개념이며 1:1 대응하지 않는다.
섞으면 GPS 샘플링 방식을 바꿀 때 그래프가 깨진다.

Route A/B는 간선의 속성이 아니라 **간선들의 조합**이다. Edge에 `route` 필드를
두지 않고 `compare.py` 결과에서 관리한다.

## 프로파일

의료적 라벨이 아니라 제약과 선호의 집합이다. 특정 신체 조건을 가진 사람이
무엇을 선호하는지 시스템이 단정하지 않는다. 아래는 데모용 프리셋이며
사용자가 값을 조정할 수 있다.

| | stairs | 문턱 | 최대 경사 | 특징 |
|---|---|---|---|---|
| default | 허용 | 100cm | 90° | 거리 우선 |
| wheelchair | **불가** | 2cm | 8° | 경사·노면·폭 민감 |
| luggage | 허용 | 10cm | 90° | 계단 단수에 큰 페널티 |

## 현재까지 측정으로 확인된 사실

실측 기반이며, 설계 결정의 근거다.

모두 **예비 측정(preliminary test)** 결과다. 실패한 결과를 과도하게
일반화하지 않도록 표현에 주의한다.

| 항목 | 예비 측정 결과 |
|---|---|
| 야외 GPS 로깅 | 검증됨. 캠퍼스 건물 밀집 구간에서 **기기가 보고한** 수평 정확도 중앙값 약 4.7m, 전 구간 6.6m 이내, 로깅 공백 없음. (지상 기준점 대비 실제 오차를 측정한 것은 아니다) |
| GPS 고도 | 예비 측정에서 국소 경사 추정에 **신뢰할 수 없다고 판단**. 정지 상태에서 14.7m 범위로 흔들렸고, 실제 계단 구간(+4.3m)보다 평지 구간의 허위 변화(+9.9m)가 컸다 |
| 보행 중 스마트폰 가속도 | 예비 측정에서 **정량적 거칠기 추정의 근거로는 불충분**. 구간별 RMS 변동이 1.8배에 그쳤고 보행 속도를 따라갔다 |
| 폰 IMU 연속성 | 100Hz, 425초 연속 로깅에서 결손 없음 |

따라서 이번 학기에는 경사와 층 이동을 현장 실측으로 채우고, 노면은 영상 분류로
판정한다. 진동 기반 거칠기는 바퀴 플랫폼에서 재검토한다.

## 주의

`data/routing_demo/entrances.json`의 개방 시간은 **예시값**이다. 현장 확인 후
실제 값으로 교체하고 `verified_at`을 갱신할 것. 잘못된 개방 정보는
정보가 없는 것보다 위험하다.

## 아직 확정되지 않은 것

Rubik Pi의 실행 경로는 **검증 전이다.** 현재 확인된 것은 Ubuntu 24.04 부팅과
SSH 접속까지이며, CSI 카메라·`qtiqmmfsrc`·NPU 추론은 파트너가 검증 중이다.

QCS6490은 QNN/HTP 경로도 있으므로 `TFLite INT8`로 아키텍처를 확정하지 않는다.
`inference/`는 인터페이스만 두고 백엔드를 나중에 채운다.

    inference/
    ├── interface.py
    ├── torch_backend.py      # 현재 개발 PC
    └── edge_backend.py       # Rubik. 실행 경로 확정 후 구현
