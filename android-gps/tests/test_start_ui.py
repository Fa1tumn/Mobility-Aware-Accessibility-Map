"""Run with requirements-desktop installed; Android APIs are test doubles."""
from pathlib import Path
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('KIVY_HOME',str(ROOT.parent/'.android-build/kivy-test-home'))
os.environ.setdefault('KIVY_NO_ARGS','1')
HAS_KIVY=importlib.util.find_spec('kivy') is not None
if HAS_KIVY:
    import main
    from kivy.clock import Clock


@unittest.skipUnless(HAS_KIVY,'Install requirements-desktop.txt for UI regression tests')
class StartUiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        folder=self.temp.name
        class TestApp(main.RubikGpsApp):
            @property
            def user_data_dir(self): return folder
        self.platform_patch=patch.object(main,'ANDROID',True)
        self.platform_patch.start()
        self.bridge=types.ModuleType('android_bridge')
        self.permission_callback=None
        self.starts=[]
        self.stops=[]
        self.bridge.request_start_permissions=self.capture_permission_request
        self.bridge.has_location_permission=lambda: True
        self.bridge.location_enabled=lambda: True
        self.bridge.start_service=lambda endpoint,error: self.starts.append(endpoint)
        self.bridge.stop_service=lambda: self.stops.append(True)
        self.modules=patch.dict(sys.modules,{'android_bridge':self.bridge})
        self.modules.start()
        self.app=TestApp()
        self.app.root=self.app.build()
        self.app.address.text='10.248.200.101'

    def tearDown(self):
        Clock.unschedule(self.app.tick)
        self.modules.stop()
        self.platform_patch.stop()
        self.temp.cleanup()

    def capture_permission_request(self,callback,error):
        self.permission_callback=callback
        self.permission_error=error

    def test_button_click_has_immediate_visible_feedback(self):
        self.app.start_button.dispatch('on_release')
        self.assertEqual(self.app.address.text,'http://10.248.200.101:8000/gps')
        self.assertTrue(self.app.start_button.disabled)
        self.assertTrue(self.app.pending_start)
        self.assertIn('권한',self.app.action_status.text)
        self.assertEqual(self.starts,[])
        self.permission_callback(True)
        Clock.tick()
        self.assertTrue(self.app.active)
        self.assertEqual(self.starts,['http://10.248.200.101:8000/gps'])

    def test_permission_denial_is_visible_and_allows_retry(self):
        self.app.start_upload()
        self.permission_callback(False)
        Clock.tick()
        self.assertFalse(self.app.start_button.disabled)
        self.assertFalse(self.app.active)
        self.assertIn('정확한 위치 권한',self.app.action_status.text)
        self.assertEqual(self.starts,[])

    def test_timeout_recovers_and_ignores_late_permission_callback(self):
        self.app.start_upload()
        self.app.permission_timeout(self.app.attempt)
        self.assertFalse(self.app.start_button.disabled)
        self.assertIn('완료되지',self.app.action_status.text)
        self.permission_callback(True)
        Clock.tick()
        self.assertEqual(self.starts,[])

    def test_permission_exception_is_shown(self):
        self.bridge.request_start_permissions=lambda *args: (_ for _ in ()).throw(RuntimeError('permission API failed'))
        self.app.start_upload()
        self.assertFalse(self.app.start_button.disabled)
        self.assertIn('시작 실패',self.app.action_status.text)

    def test_location_disabled_does_not_start_service(self):
        self.bridge.location_enabled=lambda: False
        self.app.start_upload()
        self.permission_callback(True)
        Clock.tick()
        self.assertFalse(self.app.start_button.disabled)
        self.assertIn('위치 기능',self.app.action_status.text)
        self.assertEqual(self.starts,[])

    def test_cancel_does_not_start_service_after_permission_result(self):
        self.app.start_upload()
        self.app.stop_upload()
        self.permission_callback(True)
        Clock.tick()
        self.assertEqual(self.starts,[])
        self.assertEqual(self.stops,[])
        self.assertEqual(self.app.action_status.text,'중지됨')

    def test_invalid_address_error_is_next_to_start_button(self):
        self.app.address.text=''
        self.app.start_upload()
        self.assertIn('IP 주소',self.app.action_status.text)
        self.assertFalse(self.app.start_button.disabled)

    def test_leaving_app_releases_input_focus(self):
        self.app.address.focus=True
        self.assertTrue(self.app.on_pause())
        self.assertFalse(self.app.address.focus)

    def test_indoor_coordinate_and_unrestricted_accuracy_notice_are_visible(self):
        self.app.set_active(True)
        self.app.receive(dict(running=True,status='참고 위치를 표시합니다',latitude=37.5,longitude=127.5,
            accuracy_m=350,source='network',fix_age_s=0.4,quality='오차 제한 없음 · Pi에서 사용 여부를 판단합니다',
            successful=0,failed=0,skipped=0,last_success=None))
        self.assertIn('37.5000000',self.app.fix_label.text)
        self.assertIn('350.0 m',self.app.fix_label.text)
        self.assertIn('네트워크',self.app.quality_label.text)
        self.assertIn('0.4초 전',self.app.quality_label.text)
        self.assertIn('오차 제한 없음',self.app.quality_label.text)
        self.app.stop_upload()
        self.assertNotIn('37.5',self.app.fix_label.text)
        self.assertEqual(self.app.quality_label.text,'위치 수집 중지됨')


if __name__=='__main__':
    unittest.main()
