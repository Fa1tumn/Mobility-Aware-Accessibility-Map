from pathlib import Path
import sys
import threading
import json
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import UploadEngine
from protocol import Fix


class EngineTests(unittest.TestCase):
    def test_invalid_and_stale_filter_and_stop(self):
        calls = []
        engine = UploadEngine('127.0.0.1', clock=lambda: 100, sender=lambda *args: calls.append(args))
        engine.submit(Fix(37, 127, -1, 100))
        engine.submit(Fix(37, 127, 1, 98))
        engine.submit(Fix(float('nan'), 127, 1, 100))
        self.assertEqual(engine.snapshot()['skipped'], 3)
        engine.stop()
        engine.submit(Fix(37, 127, 1, 100))
        self.assertEqual(calls, [])
        self.assertFalse(engine.thread.is_alive())
        self.assertIsNone(engine.snapshot()['latitude'])

    def test_latest_only_and_retry_with_new_fix(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        calls = []
        def sender(endpoint, fix, clock):
            calls.append(fix.latitude)
            if len(calls) == 1:
                entered.set()
                release.wait(2)
                raise OSError('disconnected')
            finished.set()
        engine = UploadEngine('127.0.0.1', clock=lambda: 100, sender=sender)
        try:
            engine.submit(Fix(1, 2, 3, 100))
            self.assertTrue(entered.wait(1))
            engine.submit(Fix(2, 2, 3, 100))
            engine.submit(Fix(3, 2, 3, 100))
            release.set()
            self.assertTrue(finished.wait(1))
        finally:
            release.set()
            engine.stop()
        self.assertEqual(calls, [1, 3])
        self.assertEqual(engine.snapshot()['skipped'], 1)
        self.assertEqual(engine.snapshot()['failed'], 1)

    def test_lost_satellite_status(self):
        now = [100.0]
        engine = UploadEngine('127.0.0.1', clock=lambda: now[0], sender=lambda *args: None)
        try:
            engine.submit(Fix(37, 127, 15, 100))
            now[0] = 104
            self.assertIn('새 위치가 없습니다', engine.snapshot()['status'])
        finally:
            engine.stop()

    def test_indoor_network_position_is_displayed_and_uploaded_at_any_accuracy(self):
        calls, uploaded = [], threading.Event()
        def sender(endpoint, fix, clock):
            calls.append(fix)
            uploaded.set()
        engine = UploadEngine('127.0.0.1', clock=lambda: 100, sender=sender)
        try:
            for accuracy in (350, 5):
                uploaded.clear()
                engine.submit(Fix(37.5, 127.2, accuracy, 99.9 if accuracy == 350 else 100), source='network')
                self.assertTrue(uploaded.wait(1))
                state = engine.snapshot()
                self.assertEqual((state['latitude'], state['accuracy_m'], state['source']), (37.5, accuracy, 'network'))
                self.assertIn('오차 제한 없음', state['quality'])
        finally:
            engine.stop()
        self.assertEqual([fix.accuracy_m for fix in calls], [350, 5])

    def test_inaccurate_satellite_position_is_displayed_and_uploaded(self):
        calls, uploaded = [], threading.Event()
        def sender(endpoint, fix, clock):
            calls.append(fix)
            uploaded.set()
        engine = UploadEngine('127.0.0.1', clock=lambda: 100, sender=sender)
        try:
            engine.submit(Fix(37, 127, 250, 100))
            self.assertTrue(uploaded.wait(1))
            state = engine.snapshot()
            self.assertEqual(state['accuracy_m'], 250)
            self.assertEqual(state['source'], 'gps')
            self.assertIn('오차 제한 없음', state['quality'])
        finally:
            engine.stop()
        self.assertEqual([fix.accuracy_m for fix in calls], [250])

    def test_latest_network_callback_is_displayed_and_uploaded_after_gps(self):
        now, uploaded = [100.0], threading.Event()
        calls = []
        def sender(endpoint, fix, clock):
            calls.append(fix)
            uploaded.set()
        engine = UploadEngine('127.0.0.1', clock=lambda: now[0], sender=sender)
        try:
            gps = Fix(37, 127, 4, 100)
            engine.submit(gps)
            self.assertTrue(uploaded.wait(1))
            now[0] = 101
            uploaded.clear()
            engine.submit(Fix(38, 128, 2, 101), source='network')
            self.assertTrue(uploaded.wait(1))
            self.assertEqual(engine.snapshot()['source'], 'network')
            now[0] = 104
            uploaded.clear()
            engine.submit(Fix(38, 128, 250, 104), source='network')
            self.assertTrue(uploaded.wait(1))
            self.assertEqual(engine.snapshot()['source'], 'network')
        finally:
            engine.stop()
        self.assertEqual([fix.accuracy_m for fix in calls], [4, 2, 250])

    def test_delayed_provider_does_not_replace_newer_pending_upload(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def sender(endpoint, fix, clock):
            calls.append(fix)
            entered.set()
            release.wait(1)
        engine = UploadEngine('127.0.0.1', clock=lambda: 100, sender=sender)
        try:
            newest = Fix(37, 127, 500, 100)
            engine.submit(newest, source='gps')
            self.assertTrue(entered.wait(1))
            engine.submit(Fix(38, 128, 250, 99.5), source='network')
            self.assertIsNone(engine.pending)
            self.assertEqual(engine.snapshot()['source'], 'gps')
        finally:
            release.set()
            engine.stop()
        self.assertEqual(calls, [newest])

    def test_recent_cache_is_labelled_and_old_cache_is_ignored(self):
        now = [200.0]
        calls = []
        engine = UploadEngine('127.0.0.1', clock=lambda: now[0], sender=lambda *args: calls.append(args))
        try:
            engine.submit(Fix(36, 126, 1, 50), source='gps', cached=True)
            self.assertIsNone(engine.snapshot()['latitude'])
            engine.submit(Fix(37, 127, 5, 190), source='gps', cached=True)
            state = engine.snapshot()
            self.assertEqual(state['latitude'], 37)
            self.assertEqual(state['fix_age_s'], 10)
            self.assertIn('이전 위치', state['quality'])
            self.assertIn('전송 안 함', state['quality'])
            engine.submit(Fix(38, 128, 2, 189), source='gps', cached=True)
            self.assertEqual(engine.snapshot()['latitude'], 37)
        finally:
            engine.stop()
        self.assertEqual(calls, [])

    def test_invalid_network_fix_never_reaches_ui_json(self):
        engine = UploadEngine('127.0.0.1', clock=lambda: 100, sender=lambda *args: None)
        try:
            for fix in (Fix(float('nan'), 127, 5, 100), Fix(91, 127, 5, 100), Fix(37, 127, 5, 101)):
                engine.submit(fix, source='network')
                self.assertIsNone(engine.snapshot()['latitude'])
                json.dumps(engine.snapshot(), allow_nan=False)
        finally:
            engine.stop()


if __name__ == '__main__':
    unittest.main()
