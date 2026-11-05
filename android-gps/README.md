# Rubik GPS — Python / 한국어

휴대폰 GPS를 Rubik Pi로 전송하는 Android 앱입니다. 화면과 알림, 앱 오류 안내는 한국어로 제공됩니다. 앱 코드는 Python으로 작성했으며 Kivy와 PyJNIus로 Android 위치 API를 사용합니다. Google Play 서비스는 필요하지 않습니다.

설치 파일: `dist/Rubik-GPS-Python-ko-v1.1.4-debug.apk` (약 23MB). 개인 테스트용 디버그 서명 APK입니다. 소스 압축 파일은 `dist/Rubik-GPS-Python-source.zip`에 있습니다.

버전 1.1.4는 휴대폰의 오차 제한을 제거합니다. 새로 받은 위성 GPS와 Android 네트워크 위치를 모두 Pi로 전송하며, 보고된 오차 `accuracy_m`은 수정하지 않습니다. 사용할 위치의 오차 기준은 Pi에서 설정합니다. 화면에는 좌표, 오차, 위치 출처와 측정 후 경과 시간을 표시합니다. 시작 시 2분 이내의 시스템 저장 위치가 있으면 이전 위치임을 표시하고 새 위치를 기다리며, 저장 위치를 다시 전송하지 않습니다. 실내에서 운영체제가 위치를 제공하지 못하면 좌표가 표시되지 않을 수 있습니다.

버전 1.1.2는 S25에서 확인한 Java 문자열 변환 문제를 수정합니다. 내부 상태 메시지가 문자 배열로 전달되거나 알림의 중지 버튼을 생성할 때 메서드 선택이 실패하던 문제를 해결했습니다. 앱을 떠나거나 전송을 시작할 때 주소 입력의 키보드 포커스를 해제하며, 서비스 오류의 자세한 내용은 앱 로그에 남깁니다.

버전 1.1.1에서는 위치·알림 권한을 Android UI 스레드에서 순서대로 요청합니다. 전송 시작을 누르면 버튼 옆에 즉시 상태를 표시하며, 권한 결과가 돌아오지 않으면 30초 뒤 재시도 안내를 표시합니다. 준비 중 중지를 누르거나 권한 확인이 끝난 뒤 도착한 이전 콜백이 서비스를 시작하지 않도록 처리했습니다.

## 사용 방법

1. 빌드된 APK를 휴대폰으로 복사해 설치합니다. Python을 휴대폰에 따로 설치할 필요는 없습니다. 기본 빌드 대상은 **Android 8.0 이상, ARM64 기기**입니다.
2. 휴대폰과 Pi를 같은 Wi-Fi에 연결합니다. 휴대폰 핫스팟에 Pi를 연결해도 됩니다.
3. Pi의 [rubik 저장소](https://github.com/Fa1tumn/Mobility-Aware-Accessibility-Map-rubik)에서 `python3 phone.py`를 실행합니다. 전체 수집 파이프라인은 `python3 main.py`로 실행합니다. 두 프로그램은 같은 8000번 포트를 사용하므로 동시에 실행하지 않습니다.
4. Pi에서 `hostname -I`로 IP 주소를 확인합니다. 앱의 **Pi 주소**에 입력하면 `http://IP:8000/gps`로 완성됩니다. `0.0.0.0`이나 휴대폰 자신의 `127.0.0.1`을 입력하지 마세요.
5. **전송 시작**을 누르고 정확한 위치 및 알림 권한을 허용합니다. 기기의 위치 기능을 켭니다. 실내에서는 네트워크 위치도 수집하며, 화면의 출처·오차·경과 시간을 확인합니다. 좌표 표시만으로 Pi 전송 성공을 의미하지는 않습니다.
6. 새 위치를 받으면 보고된 오차의 크기와 관계없이 전송합니다. 앱에 수신 확인이 표시되고 Pi 터미널에 `Latest GPS`가 출력되면 전송이 연결된 것입니다. 앱 또는 알림의 **전송 중지**로 종료합니다.

시작한 뒤 화면을 끄거나 다른 앱으로 이동해도 별도 전경 서비스가 수집합니다. 최근 앱 목록에서 앱을 제거하거나 시스템이 서비스를 종료한 경우에는 자동으로 다시 시작하지 않습니다. 제조사 절전 정책에 따라 앱의 배터리 설정에서 백그라운드 실행 허용이 필요할 수 있습니다. 실제 잠금 화면 동작은 사용할 휴대폰에서 확인해야 합니다.

## GPS 프로토콜

대상 저장소의 커밋 `bc12968724be096419b787449f5606185a79609e`, `phone.py`와 `main.py`를 기준으로 작성했습니다.

```http
POST /gps HTTP/1.1
Content-Type: application/json; charset=utf-8

{"latitude":37.5665,"longitude":126.978,"accuracy_m":4.5}
```

HTTP 200과 `{"ok":true}` 응답을 모두 확인해야 성공으로 표시합니다. IMU 데이터나 Supabase 키는 사용하지 않습니다. GPS 수신 성공은 전체 영상·IMU 관측 데이터의 저장 성공을 의미하지 않습니다.

- GPS 갱신 요청 간격은 0.5초, 네트워크 위치는 1초입니다. 실제 갱신 빈도는 휴대폰과 위치 제공자 상태에 따라 달라집니다.
- 수집 후 0.75초 이내인 새 위성 GPS와 네트워크 위치를 전송합니다. 휴대폰에서는 오차의 상한을 설정하지 않고 `accuracy_m`을 그대로 보냅니다. 기존 Pi의 `main.py`에는 `CONFIG["max_gps_accuracy_m"] = 10.0`이 있으므로, 실제 관측 데이터에 사용할 기준은 Pi에서 변경합니다. `phone.py` 단독 실행은 오차가 큰 위치도 수신하고 출력합니다.
- 네트워크 위치는 Wi-Fi·기지국 등을 이용하는 운영체제 제공 위치입니다. 데이터 연결이나 기기 위치 정확도 설정이 필요할 수 있습니다. 앱은 Google Play 서비스 SDK에 직접 의존하지 않으며, 위치 제공자의 유무는 기기에 따라 다릅니다.
- 오차가 커도 좌표를 표시하고 전송합니다. 출처와 오차로 표시를 제한하지 않으며 가장 최근에 측정된 위치를 표시합니다. 새 위치가 없으면 마지막 위치와 경과 시간을 표시합니다.
- 시작 시 2분 이내의 시스템 저장 위치만 이전 위치로 표시하며 전송하지 않습니다. 미래 시각, 범위를 벗어난 좌표, 유효하지 않은 숫자는 화면에도 표시하지 않습니다.
- 연결이 완료된 직후에도 위치의 경과 시간을 다시 확인합니다.
- 대기 중인 위치는 최신 1개만 유지합니다. 오프라인 위치를 누적하거나 마지막 좌표를 반복 전송하지 않습니다.
- 연결 실패 뒤에는 새 위치가 들어왔을 때 다시 시도합니다.

Pi는 휴대폰의 측정 시각 대신 **Pi에서 수신한 시각**을 기록합니다. 휴대폰에서 오래된 위치를 걸러내더라도 전송 중 발생하는 지연까지 제거할 수는 없습니다. 엄밀한 시간 정렬이 필요하면 Pi의 프로토콜과 시간 동기화 방식도 함께 확장해야 합니다.

## 개인정보와 연결 범위

설정한 Pi 주소만 앱 내부에 저장합니다. 좌표는 메모리와 앱 내부 전용 메시지로 처리하며 위치 이력이나 경로 파일을 만들지 않습니다. 수집 중임을 알림으로 표시하고 사용자가 직접 중지할 수 있습니다. 영구 백그라운드 위치 권한이나 부팅 시 자동 실행은 요청하지 않습니다.

기존 Pi 수신기는 인증 없는 HTTP 방식입니다. 자신의 신뢰할 수 있는 로컬 네트워크에서 사용하고 8000번 포트를 인터넷에 직접 공개하지 마세요.

## 코드 구조

| 파일 | 역할 |
| --- | --- |
| `main.py` | 한국어 Kivy 화면, 주소 입력, 권한 요청, 시작·중지 |
| `protocol.py` | 주소와 좌표 검증, HTTP 전송 및 수신 확인 |
| `engine.py` | 최신 위치만 유지하는 작업 스레드, 통계 및 상태 |
| `android_bridge.py` | Android 위치 API, 내부 메시지, 알림 |
| `services/gps_service.py` | 잠금 화면에서도 실행되는 Python 위치 서비스 |
| `errors.py` | 운영체제 오류를 한국어 안내로 변환 |
| `buildozer.spec` | APK 빌드 설정 및 권한 선언 |
| `tests/` | 프로토콜, 원본 수신기, 작업 스레드, 언어 검증 |

## PC 미리보기와 테스트

프로젝트 폴더에서 실행합니다. PC 미리보기에서는 GPS 전송 버튼이 비활성화되며 가짜 좌표를 보내지 않습니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-desktop.txt
.\.venv\Scripts\python main.py
python -m unittest discover -s tests -v
```

원본 `phone.py` 연동 테스트는 `../.reference-rubik/phone.py`가 있으면 자동으로 실행됩니다. 다른 위치라면 `RUBIK_GPS_RECEIVER` 환경변수에 파일 경로를 지정합니다. 테스트는 컴퓨터의 임시 로컬 포트에 합성 좌표만 전송합니다.

## APK 빌드

Windows에서는 WSL2의 Ubuntu를 사용합니다. 빌드는 `/mnt/c`나 `/mnt/e` 대신 Linux 내부 폴더에서 실행합니다. 이번 설정은 Python 3.14, JDK 17, Android API 35, NDK 28c와 고정된 python-for-android 커밋을 사용합니다.

Ubuntu 26.04의 기본 도구 설치:

```bash
sudo apt update
sudo apt install -y git zip unzip openjdk-17-jdk python3-venv build-essential \
  autoconf automake libtool pkg-config zlib1g-dev libncurses-dev libffi-dev \
  libssl-dev cmake gettext autopoint patch ccache rustc cargo
```

소스를 Linux 폴더에 복사한 뒤:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install git+https://github.com/kivy/buildozer setuptools legacy-cgi cython==0.29.34
buildozer -v android debug
```

반드시 가상환경을 `source`로 활성화한 뒤 실행합니다. 결과 APK는 `bin/`에 생성됩니다. 첫 빌드는 SDK·NDK 다운로드와 Python, Kivy의 네이티브 라이브러리 컴파일이 필요합니다. 설정에는 자동 빌드를 위한 SDK 라이선스 수락 옵션이 포함되어 있습니다.

서비스 구성은 [python-for-android 서비스 문서](https://python-for-android.readthedocs.io/en/latest/services.html), 빌드 환경은 [Buildozer 설치 문서](https://buildozer.readthedocs.io/en/latest/installation/)를 참고했습니다. 시스템 권한 창의 언어는 휴대폰의 시스템 언어 설정을 따릅니다.

## 휴대폰 확인 항목

1.1.4는 GPS와 네트워크 위치의 오차 제한 없는 전송, 원본 `phone.py`에 대한 실제 HTTP 수신, 위치 출처 표시, 이전 위치 재전송 방지, 유효하지 않은 좌표 차단을 PC 테스트로 확인합니다. APK의 서명과 포함된 Python 코드도 검증합니다. 실제 1.1.4의 S25 실내 위치 수신은 휴대폰에서 확인해야 합니다.

이전 버전 1.1.2는 Samsung Galaxy S25(SM-S931N, Android 16)에 USB로 설치했고 정확한 위치·알림 권한 창과 전경 서비스, 알림 생성, 화면 상태 갱신을 확인했습니다. 휴대폰에서 Pi의 8000번 포트까지 HTTP 접속도 확인했습니다. 실내에서 위성 위치를 받지 못해 실제 GPS 좌표의 Pi 수신은 아직 확인하지 못했습니다.

실내 위치가 나오지 않으면 모바일 데이터와 기기의 위치 정확도 향상 설정을 확인해 주세요. 실제 Pi 전송은 앱의 성공 횟수와 Pi의 `Latest GPS` 출력을 함께 확인합니다. 네트워크 위치의 동작과 저장 위치의 의미는 [Android LocationManager 문서](https://developer.android.com/reference/android/location/LocationManager)를 따릅니다.

정확한 위치 권한 허용·거부, 실외 첫 위치 수신, 위치 기능 끄기·켜기, Wi-Fi 끊기·복구, 5분 이상 화면 잠금, 알림에서 중지, 앱 재실행을 확인합니다. PC 테스트와 화면 미리보기만으로 실제 GPS 정확도나 제조사 절전 동작을 검증할 수는 없습니다.

앱에 포함된 `RubikGpsSans.otf`는 SIL Open Font License의 Noto Sans CJK KR에서 한글과 필요한 기호를 추린 글꼴입니다. 수정된 글꼴 이름을 사용하며 라이선스는 `assets/OFL.txt`에 포함되어 있습니다.
