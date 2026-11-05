"""Separate Python process hosted by python-for-android's foreground service."""
import json
import os
import threading
import traceback
from jnius import autoclass
from engine import UploadEngine
from android_bridge import AndroidCollector, clock
from errors import display_error


def main():
    context = autoclass("org.kivy.android.PythonService").mService
    options = json.loads(os.environ["PYTHON_SERVICE_ARGUMENT"])
    engine = UploadEngine(options["endpoint"], clock=clock)
    stopping = threading.Event()
    collector = AndroidCollector(context, engine, stopping)
    failure = None
    try:
        print("[RUBIK_GPS] Starting location collector", flush=True)
        collector.start()
        print("[RUBIK_GPS] Location collector ready", flush=True)
        ticks = 0
        while not stopping.wait(0.5):
            collector.publish()
            ticks += 1
            if ticks % 2 == 0:
                collector.notify()
    except Exception as exc:
        traceback.print_exc()
        failure = "위치 서비스 오류: " + display_error(exc)
        engine.message(failure)
        collector.publish()
    finally:
        try:
            collector.close()
        finally:
            engine.stop()
        if failure:
            engine.message(failure)
        collector.publish()
        print("[RUBIK_GPS] Location service finished", flush=True)
        # Returning ends p4a's service and removes the foreground notification.


if __name__ == "__main__":
    main()
