"""Kivy UI. Run on desktop for preview, or package with Buildozer for real GPS."""
import json
import os
from pathlib import Path
import time
import logging

os.environ.setdefault("KIVY_NO_ARGS", "1")
from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.utils import platform
from protocol import normalize_endpoint
from errors import display_error

ANDROID = platform == "android"
INK = (0.10, 0.17, 0.23, 1)
TEAL = (0.03, 0.49, 0.55, 1)
MUTED = (0.40, 0.46, 0.52, 1)
FONT = str(Path(__file__).parent / "assets/RubikGpsSans.otf")
LOG = logging.getLogger("rubik_gps")
if Path(FONT).is_file():
    LabelBase.register(name="RubikSans", fn_regular=FONT)
else:
    FONT = "Roboto"


def label(text, size=16, color=INK):
    widget = Label(text=text, font_name=FONT, font_size=dp(size), color=color,
                   halign="left", valign="middle", size_hint_y=None, height=dp(30))
    widget.bind(width=lambda w, value: setattr(w, "text_size", (max(1, value), None)))
    widget.bind(texture_size=lambda w, value: setattr(w, "height", max(dp(26), value[1] + dp(8))))
    return widget


class Card(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", size_hint_y=None, padding=dp(18), spacing=dp(10), **kwargs)
        self.bind(minimum_height=self.setter("height"))
        with self.canvas.before:
            Color(1, 1, 1, 1)
            self.shape = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(18)])
        self.bind(pos=self._shape, size=self._shape)

    def _shape(self, *_):
        self.shape.pos, self.shape.size = self.pos, self.size


def button(text, callback, primary=False):
    result = Button(text=text, font_name=FONT, font_size=dp(17), size_hint_y=None,
                    height=dp(50), background_normal="", background_down="",
                    background_color=TEAL if primary else (0.88, 0.93, 0.95, 1),
                    color=(1, 1, 1, 1) if primary else INK)
    result.bind(on_release=callback)
    return result


class RubikGpsApp(App):
    title = "Rubik GPS · Python"

    @property
    def user_data_dir(self):
        if not ANDROID and os.environ.get("RUBIK_GPS_PREVIEW_OUTPUT"):
            folder = Path(os.environ["RUBIK_GPS_PREVIEW_OUTPUT"]).parent / "preview-data"
            folder.mkdir(parents=True, exist_ok=True)
            return str(folder)
        return super().user_data_dir

    def build(self):
        Window.clearcolor = (0.95, 0.96, 0.98, 1)
        if not ANDROID:
            Window.size = (420, 860)
        self.receiver = None
        self.active = False
        self.pending_start = False
        self.attempt = 0
        self.last_status_received = 0.0
        self.start_requested = 0.0
        self.last_state = {}
        self.config_path = Path(self.user_data_dir) / "gps-config.json"
        endpoint = ""
        try:
            endpoint = json.loads(self.config_path.read_text(encoding="utf-8")).get("endpoint", "")
        except (OSError, ValueError):
            pass
        scroll = ScrollView(do_scroll_x=False)
        with scroll.canvas.before:
            Color(0.95, 0.96, 0.98, 1)
            background = Rectangle(pos=scroll.pos, size=scroll.size)
        scroll.bind(pos=lambda w, value: setattr(background, "pos", value),
                    size=lambda w, value: setattr(background, "size", value))
        page = BoxLayout(orientation="vertical", size_hint_y=None, padding=dp(22), spacing=dp(18))
        page.bind(minimum_height=page.setter("height"))
        scroll.add_widget(page)
        header = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(5))
        header.bind(minimum_height=header.setter("height"))
        header.add_widget(label("RUBIK  /  현장 수집", 12, TEAL))
        header.add_widget(label("휴대폰 GPS 전송", 29))
        header.add_widget(label("실시간 위치를 Rubik Pi로 전송합니다", 14, MUTED))
        header.add_widget(label("버전 1.1.4", 12, MUTED))
        page.add_widget(header)
        connection = Card()
        connection.add_widget(label("01   기기 연결", 19))
        connection.add_widget(label("Pi 주소", 13, MUTED))
        self.address = TextInput(text=endpoint, hint_text="예: 192.168.1.100", multiline=False,
                                 font_name=FONT, font_size=dp(17), size_hint_y=None, height=dp(48),
                                 padding=[dp(10), dp(12)], foreground_color=INK,
                                 background_normal="", background_active="", background_color=(0.95, 0.97, 0.98, 1))
        connection.add_widget(self.address)
        connection.add_widget(label("휴대폰과 Pi를 같은 Wi-Fi에 연결하거나 Pi를 휴대폰 핫스팟에 연결해 주세요. 기본 포트는 8000입니다.", 13, MUTED))
        self.action_status = label("Pi 주소를 입력하고 전송 시작을 눌러 주세요", 14, TEAL)
        connection.add_widget(self.action_status)
        self.start_button = button("전송 시작", self.start_upload, True)
        self.stop_button = button("전송 중지", self.stop_upload)
        self.stop_button.disabled = True
        connection.add_widget(self.start_button)
        connection.add_widget(self.stop_button)
        page.add_widget(connection)
        live = Card()
        self.running_label = label("위치 수집 중지됨", 19, TEAL)
        self.status_label = label("시작 전", 14)
        self.fix_label = label("위도  —\n경도  —\n오차  —", 19)
        self.quality_label = label("아직 위치를 받지 못했습니다", 14, MUTED)
        self.counts_label = label("0 성공    0 실패    0 건너뜀", 14)
        self.time_label = label("최근 전송  —", 13, MUTED)
        for widget in (self.running_label, self.status_label, self.fix_label, self.quality_label, self.counts_label, self.time_label):
            live.add_widget(widget)
        page.add_widget(live)
        guide = Card()
        guide.add_widget(label("사용 안내", 19))
        guide.add_widget(label("위성 GPS와 네트워크 위치를 모두 Pi로 전송합니다.\n휴대폰에서는 오차 제한을 적용하지 않습니다.\n보고된 오차를 함께 전송하므로 Pi에서 사용 기준을 설정해 주세요.\n이전 저장 위치는 표시만 하며 재전송하지 않습니다.\n화면이 꺼져도 수집하며 알림에서 중지할 수 있습니다. 이동 경로는 저장하지 않습니다.", 14, MUTED))
        guide.add_widget(button("기기 위치 설정", self.open_location))
        guide.add_widget(button("앱 권한 설정", self.open_permissions))
        page.add_widget(guide)
        if not ANDROID:
            self.status_label.text = "PC 미리보기입니다. GPS 수집은 Android 앱에서 사용할 수 있습니다."
            self.start_button.disabled = True
        Clock.schedule_interval(self.tick, 1)
        # UI smoke test is explicit, never generates locations or network traffic.
        if os.environ.get("RUBIK_GPS_PREVIEW_OUTPUT"):
            Clock.schedule_once(self.save_preview, 3)
        return scroll

    def on_start(self):
        if ANDROID:
            try:
                import android_bridge as bridge
                self.receiver = bridge.status_receiver(lambda state: Clock.schedule_once(lambda dt: self.receive(state), 0))
                self.set_active(bridge.is_running())
                if self.active:
                    self.set_status("실행 중인 위치 서비스에 연결하고 있습니다")
            except Exception as exc:
                LOG.exception("Android bridge initialization failed")
                self.start_error(exc)

    def set_status(self, text):
        self.action_status.text = text
        self.status_label.text = text

    def set_active(self, active):
        self.active = active
        busy = active or self.pending_start
        self.start_button.disabled = busy or not ANDROID
        self.stop_button.disabled = not busy
        self.address.disabled = busy
        self.running_label.text = "시작 준비 중" if self.pending_start else ("위치 수집 중" if active else "위치 수집 중지됨")

    def start_upload(self, *_):
        if not ANDROID or self.active or self.pending_start:
            return
        self.address.focus = False
        Window.release_all_keyboards()
        try:
            endpoint = normalize_endpoint(self.address.text)
        except ValueError as exc:
            self.set_status(str(exc))
            return
        self.address.text = endpoint
        self.attempt += 1
        attempt = self.attempt
        self.pending_start = True
        self.set_active(False)
        self.set_status("위치 및 알림 권한을 확인하고 있습니다")
        LOG.info("Start requested: checking Android permissions")
        Clock.schedule_once(lambda dt: self.permission_timeout(attempt), 30)
        try:
            import android_bridge as bridge
            bridge.request_start_permissions(
                lambda granted: Clock.schedule_once(lambda dt: self.permissions_ready(attempt, endpoint, granted), 0),
                lambda error: Clock.schedule_once(lambda dt: self.permission_error(attempt, error), 0))
        except Exception as exc:
            LOG.exception("Permission request failed")
            self.permission_error(attempt, exc)

    def permissions_ready(self, attempt, endpoint, granted):
        if attempt != self.attempt or not self.pending_start:
            return
        self.pending_start = False
        self.set_active(False)
        if not granted:
            self.set_status("정확한 위치 권한이 필요합니다. 아래 앱 권한 설정에서 허용해 주세요.")
            return
        self.launch(endpoint)

    def permission_error(self, attempt, error):
        if attempt == self.attempt:
            self.start_error(error)

    def permission_timeout(self, attempt):
        if attempt != self.attempt or not self.pending_start:
            return
        self.attempt += 1
        self.pending_start = False
        self.set_active(False)
        self.set_status("권한 확인이 완료되지 않았습니다. 앱 권한 설정에서 정확한 위치를 허용한 후 다시 눌러 주세요.")

    def launch(self, endpoint):
        try:
            import android_bridge as bridge
            if not bridge.has_location_permission():
                self.set_status("정확한 위치 권한이 필요합니다. 아래 앱 권한 설정에서 허용한 후 다시 시도해 주세요.")
                return
            if not bridge.location_enabled():
                self.set_status("기기의 위치 기능을 켜고 다시 시작해 주세요")
                return
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(json.dumps({"endpoint": endpoint}), encoding="utf-8")
            self.set_active(True)
            self.start_requested = time.monotonic()
            self.last_state = {}
            self.last_status_received = 0
            self.set_status("GPS 위치 서비스를 시작하고 있습니다")
            bridge.start_service(endpoint, lambda error: Clock.schedule_once(lambda dt: self.start_error(error), 0))
        except Exception as exc:
            LOG.exception("Location service launch failed")
            self.start_error(exc)

    def start_error(self, error):
        self.pending_start = False
        self.set_active(False)
        self.set_status("시작 실패: " + display_error(error))

    def stop_upload(self, *_):
        self.attempt += 1
        was_active = self.active
        self.pending_start = False
        if ANDROID and was_active:
            try:
                import android_bridge as bridge
                bridge.stop_service()
            except Exception:
                LOG.exception("Service stop failed")
        self.set_active(False)
        self.last_state = {}
        self.set_status("중지됨")
        self.fix_label.text = "위도  —\n경도  —\n오차  —"
        self.quality_label.text = "위치 수집 중지됨"

    def receive(self, state):
        # Ignore a queued broadcast from a just-stopped service.
        if not self.active:
            return
        self.last_status_received = time.monotonic()
        self.last_state = state
        self.set_status(state["status"])
        if state.get("latitude") is not None:
            self.fix_label.text = (f"위도  {state['latitude']:.7f}\n경도  {state['longitude']:.7f}"
                                   f"\n오차  ± {state['accuracy_m']:.1f} m")
            source = "위성 GPS" if state.get("source") == "gps" else "네트워크"
            self.quality_label.text = (f"출처  {source} · {state.get('fix_age_s', 0):.1f}초 전\n"
                                       + state.get("quality", ""))
        else:
            self.quality_label.text = state.get("quality", "아직 위치를 받지 못했습니다")
        self.counts_label.text = f"{state['successful']} 성공    {state['failed']} 실패    {state['skipped']} 건너뜀"
        self.time_label.text = "최근 전송  " + (state.get("last_success") or "—")
        if not state["running"]:
            self.set_active(False)
            self.fix_label.text = "위도  —\n경도  —\n오차  —"
            self.quality_label.text = "위치 수집 중지됨"

    def tick(self, _):
        if not ANDROID or not self.active:
            return
        import android_bridge as bridge
        if time.monotonic() - self.start_requested > 5 and not bridge.is_running():
            self.set_active(False)
            self.set_status("위치 서비스가 종료되었습니다. 다시 시작해 주세요. 반복되면 로그를 확인해 주세요.")
            self.fix_label.text = "위도  —\n경도  —\n오차  —"
            self.quality_label.text = "위치 수집 중지됨"
        elif time.monotonic() - max(self.last_status_received, self.start_requested) > 10:
            self.set_status("위치 서비스가 응답하지 않습니다. 중지 후 다시 시작해 주세요.")

    def open_location(self, *_):
        if ANDROID:
            from android_bridge import location_settings
            location_settings()

    def open_permissions(self, *_):
        if ANDROID:
            from android_bridge import app_settings
            app_settings()

    def on_pause(self):
        self.address.focus = False
        Window.release_all_keyboards()
        return True  # The separate foreground service continues while locked.

    def on_stop(self):
        if self.receiver:
            self.receiver.stop()

    def save_preview(self, _):
        self.root.export_to_png(os.environ["RUBIK_GPS_PREVIEW_OUTPUT"])
        self.root.scroll_y = 0
        Clock.schedule_once(self.save_preview_bottom, 0.3)

    def save_preview_bottom(self, _):
        target = Path(os.environ["RUBIK_GPS_PREVIEW_OUTPUT"])
        self.root.export_to_png(str(target.with_name(target.stem + "-bottom.png")))
        self.stop()


if __name__ == "__main__":
    RubikGpsApp().run()
