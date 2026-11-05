"""Pure Python wire protocol for rubik/phone.py. No Android/Kivy imports."""
from dataclasses import dataclass
import http.client
import json
import math
import time
from urllib.parse import urlsplit, urlunsplit

MAX_AGE_S = 0.75


def normalize_endpoint(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Pi의 IP 주소를 입력해 주세요")
    if "://" not in value:
        value = "http://" + value
    try:
        url = urlsplit(value)
        port = url.port
        if (url.scheme not in ("http", "https") or not url.hostname
                or url.username is not None or url.password is not None
                or url.query or url.fragment or "?" in value or "#" in value
                or url.path not in ("", "/", "/gps") or port == 0
                or any(c.isspace() for c in value)):
            raise ValueError()
        host = url.hostname
        if ":" in host:
            host = f"[{host}]"
        if port is None and url.scheme == "http":
            port = 8000
        authority = host if port is None else f"{host}:{port}"
        return urlunsplit((url.scheme, authority, "/gps", "", ""))
    except ValueError as exc:
        raise ValueError("Pi IP 또는 http://IP:8000/gps를 입력해 주세요") from exc


@dataclass(frozen=True)
class Fix:
    latitude: float
    longitude: float
    accuracy_m: float
    captured_s: float  # Same monotonic/boottime clock as the supplied clock().

    def invalid_reason(self, now: float) -> str | None:
        values = (self.latitude, self.longitude, self.accuracy_m, self.captured_s, now)
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
            return "위치 데이터가 올바르지 않습니다"
        if not -90 <= self.latitude <= 90 or not -180 <= self.longitude <= 180 or self.accuracy_m < 0:
            return "위치 데이터가 허용 범위를 벗어났습니다"
        if self.captured_s <= 0 or self.captured_s > now:
            return "위치 측정 시각이 올바르지 않습니다"
        return None

    def rejection(self, now: float) -> str | None:
        reason = self.invalid_reason(now)
        if reason:
            return reason
        if now - self.captured_s > MAX_AGE_S:
            return "오래된 위치입니다. 새 위치를 기다립니다"
        return None

    def body(self) -> bytes:
        return json.dumps({"latitude": self.latitude, "longitude": self.longitude,
                           "accuracy_m": self.accuracy_m}, allow_nan=False, separators=(",", ":")).encode("utf-8")


def send_fix(endpoint: str, fix: Fix, clock=time.monotonic) -> None:
    reason = fix.rejection(clock())
    if reason:
        raise ValueError(reason)
    url = urlsplit(normalize_endpoint(endpoint))
    kind = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
    connection = kind(url.hostname, url.port, timeout=0.7)
    try:
        connection.connect()
        reason = fix.rejection(clock())
        if reason:
            raise ValueError(reason)
        connection.sock.settimeout(0.8)
        connection.request("POST", "/gps", body=fix.body(), headers={
            "Content-Type": "application/json; charset=utf-8", "Connection": "close"})
        response = connection.getresponse()
        if response.status != 200:
            raise OSError(f"HTTP {response.status}: Pi 주소와 /gps 경로를 확인해 주세요")
        raw = response.read(1025)
        if len(raw) > 1024:
            raise OSError("Pi 응답이 너무 깁니다")
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise OSError("Pi 응답이 올바른 JSON이 아닙니다") from exc
        if not isinstance(body, dict) or body.get("ok") is not True:
            raise OSError('Pi 수신 확인에 실패했습니다. 예상 응답: {"ok":true}')
    finally:
        connection.close()
