"""Bounded, latest-fix-only upload worker, shared by Android and desktop tests."""
import threading
import time
from protocol import Fix, MAX_AGE_S, normalize_endpoint, send_fix
from errors import display_error


class UploadEngine:
    def __init__(self, endpoint, clock=time.monotonic, sender=send_fix):
        self.endpoint = normalize_endpoint(endpoint)
        self.clock, self.sender = clock, sender
        self.condition = threading.Condition()
        self.pending = None
        self.latest_queued_s = 0.0
        self.fixes = {}
        self.stopped = False
        self.state = dict(running=True, status="GPS 또는 네트워크 위치를 기다립니다", latitude=None,
                          longitude=None, accuracy_m=None, fix_time=None,
                          successful=0, failed=0, skipped=0, last_success=None)
        self.thread = threading.Thread(target=self._run, name="gps-upload", daemon=True)
        self.thread.start()

    def submit(self, fix: Fix, source="gps", cached=False):
        with self.condition:
            if self.stopped:
                return
            now = self.clock()
            reason = fix.invalid_reason(now)
            if reason:
                self.state["skipped"] += 1
                self.state["status"] = reason
                return
            if source not in ("gps", "network"):
                return
            # 시작 시 2분 이내의 캐시만 참고로 표시하며 전송하지 않습니다.
            if cached and now - fix.captured_s > 120:
                return
            previous = self.fixes.get(source)
            if previous is not None:
                old_fix, old_cached = previous
                if fix.captured_s < old_fix.captured_s:
                    if not cached:
                        self.state["skipped"] += 1
                    return
                if fix.captured_s == old_fix.captured_s and (cached or (not old_cached and fix == old_fix)):
                    return
            self.fixes[source] = (fix, cached)
            if cached:
                if self._display_fix(now)[0] == source:
                    self.state["status"] = "이전 위치를 표시합니다. 새 위치를 기다립니다"
                return
            reason = fix.rejection(now)
            if reason:
                self.state["skipped"] += 1
                self.state["status"] = reason
                return
            if fix.captured_s < self.latest_queued_s:
                self.state["skipped"] += 1
                return
            if self.pending is not None:
                self.state["skipped"] += 1
            self.latest_queued_s = fix.captured_s
            self.pending = fix
            self.condition.notify()

    def _display_fix(self, now):
        # 출처나 오차로 제한하지 않고 가장 최근에 측정된 위치를 표시합니다.
        return max(self.fixes.items(), key=lambda entry: entry[1][0].captured_s)

    def message(self, text):
        with self.condition:
            self.state["status"] = text

    def snapshot(self):
        with self.condition:
            result = dict(self.state)
            now = self.clock()
            result.update(source=None, fix_age_s=None, quality="아직 위치를 받지 못했습니다")
            if self.fixes:
                source, (fix, cached) = self._display_fix(now)
                age = now - fix.captured_s
                if cached or age > 3:
                    quality = "이전 위치 · 현재 위치가 아닐 수 있습니다 · Pi 전송 안 함"
                elif age > MAX_AGE_S:
                    quality = "이전 측정 위치 · 새 위치를 기다립니다"
                else:
                    quality = "오차 제한 없음 · Pi에서 사용 여부를 판단합니다"
                result.update(latitude=fix.latitude, longitude=fix.longitude, accuracy_m=fix.accuracy_m,
                              fix_time=fix.captured_s, source=source, fix_age_s=age, quality=quality)
        result["heartbeat"] = now
        result["endpoint"] = self.endpoint
        if result["running"] and result["fix_age_s"] is not None and result["fix_age_s"] > 3:
            result["status"] = "3초 이상 새 위치가 없습니다. 표시된 위치의 경과 시간을 확인해 주세요"
        return result

    def stop(self):
        with self.condition:
            self.stopped = True
            self.pending = None
            self.fixes.clear()
            self.state.update(running=False, status="중지됨", latitude=None, longitude=None,
                              accuracy_m=None, fix_time=None)
            self.condition.notify_all()
        self.thread.join(timeout=2)

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.stopped or self.pending is not None)
                if self.stopped:
                    return
                fix, self.pending = self.pending, None
            try:
                self.sender(self.endpoint, fix, self.clock)
                error = None
            except Exception as exc:
                error = display_error(exc)
            with self.condition:
                if self.stopped:
                    return
                if error:
                    self.state["failed"] += 1
                    self.state["status"] = f"전송 실패: {error}. 새 위치를 받으면 다시 시도합니다"
                else:
                    self.state["successful"] += 1
                    self.state["last_success"] = time.strftime("%H:%M:%S")
                    self.state["status"] = "전송 성공 · Pi에서 수신을 확인했습니다"
