"""Keep app-visible errors Korean even when the OS uses another locale."""
import socket


def display_error(error):
    if isinstance(error, TimeoutError):
        return "연결 시간이 초과되었습니다"
    if isinstance(error, ConnectionRefusedError):
        return "Pi에서 연결을 거부했습니다. 수신 프로그램을 확인해 주세요"
    if isinstance(error, socket.gaierror):
        return "Pi 주소를 찾을 수 없습니다"
    text = str(error)
    has_hangul = any(0xAC00 <= ord(c) <= 0xD7A3 for c in text)
    has_han = any(0x3400 <= ord(c) <= 0x9FFF or 0x20000 <= ord(c) <= 0x323AF for c in text)
    technical = any(token in text for token in ("No methods", "available:", "requested:", "Traceback", "JavaException"))
    if "Notification" in text and technical:
        return "위치 수집 알림을 만들지 못했습니다"
    if has_hangul and not has_han and len(text) <= 240 and not technical:
        return text
    return "요청을 처리할 수 없습니다. 권한과 네트워크 연결을 확인해 주세요"
