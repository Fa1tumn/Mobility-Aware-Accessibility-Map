# 출입구 등록 웹앱

휴대폰 브라우저(아이폰 Safari 포함)에서 여는 HTML 한 장이다. 설치 없이 링크로 접속해
두 사람이 같은 Supabase에 출입구를 등록한다. 위치·카메라를 쓰므로 **https 주소**로 열어야 한다.

## 화면 순서

1. **건물 선택:** 지도에서 건물을 누르거나 이름 검색. 목록에 없으면 이름을 직접 입력.
2. **출입구 위치:** '현재 위치'로 이동(최대 12초 동안 가장 정확한 값을 고름) → 빨간 핀을 실제 문에 맞춤.
   GPS 원래 위치·정확도와 사용자가 맞춘 핀을 따로 저장하고, 옮긴 거리(`pin_moved_m`)도 남긴다.
3. **사진:** 카메라로 문과 진입로를 찍는다. 긴 변 1600px JPEG로 줄여 올린다. 없이도 저장 가능.
4. **상태:** 계단·경사로·문턱은 있음/없음/모름. 계단 단수, 문턱 높이(cm), 문 종류는 선택.
5. **저장:** 출입구 이름, 운영 시간 메모, 등록한 사람.

저장하면 먼저 휴대폰(IndexedDB)에 넣고 바로 올린다. 통신이 끊겼으면 상단에 '전송 대기 N건'이
뜨고, 연결되면 자동으로(또는 눌러서) 다시 올린다. 기록 ID를 휴대폰이 정하므로 다시 보내도 한 번만 저장된다.
이미 등록된 출입구는 지도에 초록 점으로 보여서 두 사람이 겹쳐 등록하지 않게 한다.

## 준비 (한 번)

1. Supabase SQL Editor에서 `docs/sql/entrances.sql` 실행 → `entrances` 테이블, 사진 버킷 `entrance-photos`, 공개 키용 등록·조회 정책.
2. 공개 키(Settings > API Keys > Publishable key)를 확인한다. **비밀 키는 웹앱에 넣지 않는다**(앱이 거부한다).
3. 웹앱을 https로 올린다. 예: GitHub Pages(저장소 소유자가 Settings > Pages에서 켬, 주소
   `https://fa1tumn.github.io/Mobility-Aware-Accessibility-Map/web/entrance/`).
4. 팀에 설정이 들어간 링크를 공유한다. 주소 뒤 `#` 부분은 서버로 보내지지 않고 휴대폰에만 저장된다.

       https://.../web/entrance/#url=https://xxxx.supabase.co&key=sb_publishable_...

   아이폰에서 공유 버튼 > '홈 화면에 추가'를 하면 앱처럼 열린다.

## 경로 계산에 연결

    python -m scripts.import_entrances --graph data/graph/test_area.geojson \
        --out-graph output/route/graph_with_entrances.geojson --out-buildings output/route/buildings_registered.json

기록마다 출입구 노드(`kind=entrance`, 핀 위치)를 만들고 25m 안의 가장 가까운 보행로 노드와 연결 간선으로 잇는다.
계단·문턱·경사로는 그 간선에 실린다. 결과 파일은 `scripts.route`, `scripts.building_route`의 `--graph`, `--buildings`에 넣는다.

| 웹앱 값 | 연결 간선 |
|---|---|
| 계단 있음(단수 입력) / 있음(단수 모름) / 없음 / 모름 | stairs = 단수 / 1 / 0 / 0 |
| 문턱 있음(cm 입력) / 있음(높이 모름) / 없음 / 모름 | threshold_cm = 값 / 3.0(휠체어 한도 2cm보다 높은 보수값) / 0 / 0 |
| 경사로 있음 | ramp = true |
| 모름 항목 하나마다 | confidence −0.25, note에 '미확인: …' |

25m 안에 보행로 노드가 없으면 억지로 잇지 않고 건너뛴 목록에 남긴다(graph에 그 길을 먼저 그려야 한다).
건물 목록은 `scripts/build_entrance_buildings.py`로 OpenStreetMap 건물 중 캠퍼스 사각형 안의 것만 뽑은 것이다.

## 아직 안 한 것

- 가까운 보행로 후보를 앱 화면에 보여주고 "이 길로 이어짐"을 확인받기 (graph가 생긴 뒤)
- 운영 시간을 `data/campus/schedule.json` 형식으로 구조화해서 받기 (지금은 메모)
- 등록 내용 수정·삭제 (지금은 공개 키로 등록·조회만 가능)
