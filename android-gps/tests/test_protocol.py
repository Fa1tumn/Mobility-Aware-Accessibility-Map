import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from protocol import Fix, normalize_endpoint, send_fix


class ProtocolTests(unittest.TestCase):
    def test_endpoint_defaults_and_ipv6(self):
        self.assertEqual(normalize_endpoint(" 192.168.1.10 "), "http://192.168.1.10:8000/gps")
        self.assertEqual(normalize_endpoint("http://pi.local:9000/"), "http://pi.local:9000/gps")
        self.assertEqual(normalize_endpoint("https://pi.local"), "https://pi.local/gps")
        self.assertEqual(normalize_endpoint("http://[::1]:1234/gps"), "http://[::1]:1234/gps")

    def test_bad_endpoints(self):
        for value in ("", "ftp://pi", "http://u:p@pi", "http://pi/wrong", "http://pi:0",
                      "http://pi:65536", "http://pi/gps?a=1", "http://pi/#x", "http://pi/#", "http://a b"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_endpoint(value)

    def test_validity_and_age_without_accuracy_limit(self):
        self.assertIsNone(Fix(37, 127, 10, 100).rejection(100.75))
        for accuracy in (10.1, 350, 10000, 1_000_000):
            self.assertIsNone(Fix(37, 127, accuracy, 100).rejection(100))
        for fix, now in ((Fix(37, 127, 10, 100), 100.751), (Fix(37, 127, 10, 101), 100),
                         (Fix(91, 127, 1, 100), 100),
                         (Fix(1, -181, 1, 100), 100), (Fix(1, 2, -1, 100), 100),
                         (Fix(True, 2, 1, 100), 100), (Fix(float('nan'), 2, 1, 100), 100),
                         (Fix(1, 2, 1, float('inf')), 100), (Fix(1, 2, 1, 0), 0)):
            with self.subTest(fix=fix, now=now):
                self.assertIsNotNone(fix.rejection(now))

    def test_exact_wire_keys(self):
        self.assertEqual(json.loads(Fix(37.5, 127.0, 4.5, 100).body()),
                         {"latitude": 37.5, "longitude": 127.0, "accuracy_m": 4.5})


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.requests = []
        cls.reply = b'{"ok":true}'
        cls.code = 200
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                cls.requests.append((self.path, self.headers['Content-Type'], body))
                self.send_response(cls.code)
                self.send_header('Content-Length', str(len(cls.reply)))
                self.end_headers()
                self.wfile.write(cls.reply)
            def log_message(self, *args):
                pass
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/gps'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        type(self).requests.clear()
        type(self).reply = b'{"ok":true}'
        type(self).code = 200

    def test_real_http_request(self):
        send_fix(self.url, Fix(37.5665, 126.978, 350, 100), clock=lambda: 100)
        path, content_type, body = self.requests[-1]
        self.assertEqual(path, '/gps')
        self.assertIn('application/json', content_type)
        self.assertEqual(json.loads(body)['accuracy_m'], 350)

    def test_bad_acknowledgements(self):
        for body in (b'{}', b'{"ok":false}', b'{"ok":1}', b'[]', b'garbage', b'x' * 1025):
            type(self).reply = body
            with self.subTest(body=body[:20]), self.assertRaises(OSError):
                send_fix(self.url, Fix(1, 2, 3, 100), clock=lambda: 100)

    def test_http_error_and_redirect_not_followed(self):
        for code in (400, 404, 302, 503):
            type(self).code = code
            with self.subTest(code=code), self.assertRaises(OSError):
                send_fix(self.url, Fix(1, 2, 3, 100), clock=lambda: 100)

    def test_stale_never_transmitted(self):
        with self.assertRaises(ValueError):
            send_fix(self.url, Fix(1, 2, 3, 100), clock=lambda: 102)
        self.assertEqual(self.requests, [])

    def test_expired_during_connect_never_transmitted(self):
        ticks = iter([100, 102])
        with self.assertRaises(ValueError):
            send_fix(self.url, Fix(1, 2, 3, 100), clock=lambda: next(ticks))
        self.assertEqual(self.requests, [])


class OriginalReceiverTests(unittest.TestCase):
    def test_engine_uploads_indoor_position_with_original_accuracy(self):
        from engine import UploadEngine
        receiver = Path(os.environ.get('RUBIK_GPS_RECEIVER', str(Path(__file__).resolve().parents[2] / '.reference-rubik/phone.py')))
        if not receiver.is_file():
            self.skipTest('Set RUBIK_GPS_RECEIVER to the original rubik phone.py')
        spec = importlib.util.spec_from_file_location('rubik_indoor_phone', receiver)
        phone = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(phone)
        phone.CONFIG.update(host='127.0.0.1', port=0)
        state = phone.start_phone()
        delivered = threading.Event()
        def sender(endpoint, fix, clock):
            send_fix(endpoint, fix, clock)
            delivered.set()
        engine = UploadEngine(f"http://127.0.0.1:{state['server'].server_address[1]}/gps", clock=lambda: 100, sender=sender)
        try:
            for source, accuracy in (('gps', 250), ('network', 350)):
                delivered.clear()
                engine.submit(Fix(37.5, 127.5, accuracy, 100), source=source)
                self.assertTrue(delivered.wait(2), source)
                received = phone.get_latest_gps(state)
                self.assertEqual((received['latitude'], received['longitude'], received['accuracy_m']), (37.5, 127.5, accuracy))
        finally:
            engine.stop()
            phone.stop_phone(state)

    def test_original_phone_py(self):
        default = Path(__file__).resolve().parents[2] / '.reference-rubik/phone.py'
        receiver = Path(os.environ.get('RUBIK_GPS_RECEIVER', str(default)))
        if not receiver.is_file():
            self.skipTest('Set RUBIK_GPS_RECEIVER to the original rubik phone.py')
        spec = importlib.util.spec_from_file_location('rubik_phone', receiver)
        phone = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(phone)
        phone.CONFIG.update(host='127.0.0.1', port=0)
        state = phone.start_phone()
        try:
            endpoint = f"http://127.0.0.1:{state['server'].server_address[1]}/gps"
            send_fix(endpoint, Fix(37.5665, 126.978, 4.5, 100), clock=lambda: 100)
            gps = phone.get_latest_gps(state)
            self.assertEqual((gps['latitude'], gps['longitude'], gps['accuracy_m']), (37.5665, 126.978, 4.5))
            self.assertTrue(gps['gps_time'].endswith('Z'))
            self.assertGreater(gps['gps_monotonic'], 0)
            with self.assertRaises(ValueError):
                send_fix(endpoint, Fix(0, 0, 1, 100), clock=lambda: 102)
            self.assertEqual(phone.get_latest_gps(state), gps)
        finally:
            phone.stop_phone(state)


if __name__ == '__main__':
    unittest.main()
