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

두 가지 원칙을 지킨다.

- **미확인은 채우지 않는다.** '모름'을 0으로 바꾸거나, 재지 않은 계단 단수·문턱 높이를 가정값으로 넣지 않는다.
  경로 엔진의 간선은 계단 수·문턱 높이를 비워 둘 수 없으므로, 하나라도 미확인이면 graph에 넣지 않고 '현장 보완 필요'로 남긴다.
- **보행로 연결은 확인한 뒤에만.** 핀에서 25m 안의 보행로 노드를 가까운 순으로 3개까지 '후보'로 보여주고,
  사람이 확인해 `data/campus/entrance_links.json`에 적은 노드와만 잇는다.

```bash
# 1) 받아서 검토 목록 만들기 (output/route/entrance_review.json)
python -m scripts.import_entrances --graph data/graph/test_area.geojson
# 2) 후보 중 실제로 문까지 이어지는 노드를 확인해 적기
#    data/campus/entrance_links.json  →  {"links": {"<record_id>": "<보행로 노드 ID>"}}
# 3) 다시 실행 → 값이 모두 있고 연결이 확인된 출입구만 graph·건물 파일에 들어감
python -m scripts.import_entrances --graph data/graph/test_area.geojson
```

| 상태 | 뜻 | 할 일 |
|---|---|---|
| 현장 보완 필요 (`needs_survey`) | 계단·문턱·경사로 중 '모름'이 있거나, '있음'인데 단수·높이를 안 잼 | 다시 가서 확인 후 재등록 |
| 연결 확인 필요 (`needs_link`) | 값은 다 있음. 이을 보행로 미확인 | 후보를 확인해 links 파일에 적기 |
| graph에 연결됨 (`attached`) | 출입구 노드 + 연결 간선 생성 | - |
| 오류 (`invalid`) | 핀 좌표 없음, 확인한 노드가 graph에 없음 | 기록·links 확인 |

연결 간선에는 잰 값만 들어간다: 계단 단수, 문턱 높이(cm, '없음'은 0), 경사로 유무.
결과 파일(`output/route/graph_with_entrances.geojson`, `buildings_registered.json`)은
`scripts.route`, `scripts.building_route`의 `--graph`, `--buildings`에 넣는다.
graph 없이 실행하면(`--graph` 생략) 받은 기록의 미확인 항목만 점검한다.
건물 목록은 `scripts/build_entrance_buildings.py`로 OpenStreetMap 건물 중 캠퍼스 사각형 안의 것만 뽑은 것이다.

## 아직 안 한 것

- 연결 후보를 앱 화면에서 바로 확인받기 (지금은 검토 목록 + links 파일, 실험 구역 graph가 생긴 뒤)
- 운영 시간을 `data/campus/schedule.json` 형식으로 구조화해서 받기 (지금은 메모)
- 등록 내용 수정·삭제 (지금은 공개 키로 등록·조회만 가능)
