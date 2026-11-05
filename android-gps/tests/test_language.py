from pathlib import Path
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from errors import display_error


class LanguageTests(unittest.TestCase):
    def test_raw_android_overload_error_is_not_shown_in_ui(self):
        raw="No methods called addAction in android/app/Notification$Builder matching requested: (0, '전송 중지'), available: []"
        result=display_error(raw)
        self.assertEqual(result,'위치 수집 알림을 만들지 못했습니다')
        self.assertNotIn('available:',result)

    def test_system_error_language_does_not_leak(self):
        for error in (TimeoutError(), ConnectionRefusedError(), OSError('Connection reset'), chr(0x4E2D)):
            self.assertTrue(any(0xAC00 <= ord(c) <= 0xD7A3 for c in display_error(error)))
            self.assertFalse(any(0x3400 <= ord(c) <= 0x9FFF for c in display_error(error)))

    def test_no_han_characters_in_delivered_text(self):
        root = Path(__file__).resolve().parents[1]
        for path in root.rglob('*'):
            if path.suffix not in {'.py', '.md', '.spec', '.xml', '.txt'}:
                continue
            if any(part in {'.buildozer', '.venv', 'bin', 'dist', '__pycache__'} for part in path.parts):
                continue
            text = path.read_text(encoding='utf-8')
            with self.subTest(path=str(path.relative_to(root))):
                self.assertFalse(any(0x3400 <= ord(c) <= 0x9FFF or 0x20000 <= ord(c) <= 0x323AF for c in text))


if __name__ == '__main__':
    unittest.main()
