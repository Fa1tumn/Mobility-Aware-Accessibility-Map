"""Android-only interfaces. All app logic remains Python; PyJNIus calls OS APIs."""
import json
import logging
from jnius import autoclass, cast, PythonJavaClass, java_method
from android.broadcast import BroadcastReceiver
from android.runnable import run_on_ui_thread

PACKAGE = "com.fa1tumn.rubikgps"
ACTION_STATUS = PACKAGE + ".STATUS"
ACTION_STOP = PACKAGE + ".STOP"
Activity = autoclass("org.kivy.android.PythonActivity")
ServiceClass = autoclass(PACKAGE + ".ServiceGps")
Intent = autoclass("android.content.Intent")
SystemClock = autoclass("android.os.SystemClock")
LOG = logging.getLogger("rubik_gps")


def has_location_permission():
    from android.permissions import Permission, check_permission
    return check_permission(Permission.ACCESS_FINE_LOCATION)


@run_on_ui_thread
def request_start_permissions(on_result, on_error):
    """Android permission dialogs must be requested from the Activity thread."""
    from android.permissions import Permission, check_permission, request_permissions

    def finish(*_):
        try:
            on_result(has_location_permission())
        except Exception as exc:
            on_error(exc)

    def notifications(*_):
        try:
            if not has_location_permission():
                finish()
                return
            name = "android.permission.POST_NOTIFICATIONS"
            if autoclass("android.os.Build$VERSION").SDK_INT >= 33 and not check_permission(name):
                request_permissions([name], finish)
            else:
                finish()
        except Exception as exc:
            on_error(exc)

    try:
        if has_location_permission():
            notifications()
        else:
            request_permissions([Permission.ACCESS_FINE_LOCATION, Permission.ACCESS_COARSE_LOCATION], notifications)
    except Exception as exc:
        on_error(exc)


def clock():
    return SystemClock.elapsedRealtimeNanos() / 1_000_000_000


def is_running():
    manager = cast("android.app.ActivityManager", Activity.mActivity.getSystemService("activity"))
    for item in manager.getRunningServices(100).toArray():
        if item.service.getClassName() == PACKAGE + ".ServiceGps":
            return True
    return False


@run_on_ui_thread
def start_service(endpoint, on_error):
    try:
        activity = Activity.mActivity
        intent = ServiceClass.getDefaultIntent(activity, "", "Rubik GPS", "GPS 위치를 확인하고 있습니다", json.dumps({"endpoint": endpoint}))
        activity.startForegroundService(intent)
    except Exception as exc:
        on_error(str(exc))


def stop_service():
    # Explicit user Stop; stopping the service also removes its notification.
    ServiceClass.stop(Activity.mActivity)


def status_receiver(callback):
    def received(context, intent):
        try:
            callback(json.loads(intent.getStringExtra("state")))
        except (ValueError, TypeError):
            pass
    receiver = BroadcastReceiver(received, actions=[ACTION_STATUS], exported=False)
    receiver.start()
    return receiver


def location_settings():
    Activity.mActivity.startActivity(Intent("android.settings.LOCATION_SOURCE_SETTINGS"))


def location_enabled():
    manager = cast("android.location.LocationManager", Activity.mActivity.getSystemService("location"))
    return any(manager.isProviderEnabled(provider) for provider in location_providers(manager))


def location_providers(manager):
    available = {str(provider) for provider in manager.getAllProviders().toArray()}
    return [provider for provider in ("gps", "network") if provider in available]


def app_settings():
    Uri = autoclass("android.net.Uri")
    Activity.mActivity.startActivity(Intent("android.settings.APPLICATION_DETAILS_SETTINGS", Uri.parse("package:" + PACKAGE)))


class LocationListener(PythonJavaClass):
    __javainterfaces__ = ["android/location/LocationListener"]
    __javacontext__ = "app"

    def __init__(self, engine):
        super().__init__()
        self.engine = engine

    @java_method("(Landroid/location/Location;)V")
    def onLocationChanged(self, location):
        self.accept(location)

    def accept(self, location, cached=False):
        from protocol import Fix
        if not location.hasAccuracy():
            self.engine.message("정확도 정보가 없습니다. 새 위치를 기다립니다")
            return
        self.engine.submit(Fix(location.getLatitude(), location.getLongitude(), location.getAccuracy(),
                               location.getElapsedRealtimeNanos() / 1_000_000_000),
                           source=str(location.getProvider()), cached=cached)

    @java_method("(Ljava/util/List;)V", name="onLocationChanged")
    def onLocationChangedList(self, locations):
        # Android 12+ may deliver a batch. Only consider its latest sample.
        if locations.size() > 0:
            newest = cast("android.location.Location", locations.get(locations.size() - 1))
            self.onLocationChanged(newest)

    @java_method("(Ljava/lang/String;)V")
    def onProviderDisabled(self, provider):
        self.engine.message("일부 위치 기능이 꺼졌습니다. 기기 위치 설정을 확인해 주세요")

    @java_method("(Ljava/lang/String;)V")
    def onProviderEnabled(self, provider):
        self.engine.message("위치 기능이 켜졌습니다. GPS 또는 네트워크 위치를 기다립니다")

    @java_method("(Ljava/lang/String;ILandroid/os/Bundle;)V")
    def onStatusChanged(self, provider, status, extras):
        pass


class AndroidCollector:
    def __init__(self, context, engine, stop_event):
        self.context, self.engine = context, engine
        self.listener = LocationListener(engine)
        self.manager = cast("android.location.LocationManager", context.getSystemService("location"))
        self.wake_lock = None
        self.receiver = BroadcastReceiver(lambda *args: stop_event.set(), actions=[ACTION_STOP], exported=False)

    def start(self):
        self.receiver.start()
        power = cast("android.os.PowerManager", self.context.getSystemService("power"))
        self.wake_lock = power.newWakeLock(1, "rubikgps:collection")
        self.wake_lock.acquire()
        providers = location_providers(self.manager)
        if not providers:
            raise RuntimeError("이 기기에서 위치 제공자를 찾을 수 없습니다")
        if not any(self.manager.isProviderEnabled(provider) for provider in providers):
            self.engine.message("기기 설정에서 위치 기능을 켜 주세요")
        registered = []
        for provider in providers:
            try:
                interval = 500 if provider == "gps" else 1000
                self.manager.requestLocationUpdates(provider, interval, 0.0, self.listener,
                                                    autoclass("android.os.Looper").getMainLooper())
                registered.append(provider)
            except Exception:
                LOG.exception("Location provider registration failed: %s", provider)
        if not registered:
            raise RuntimeError("위치 수집을 시작하지 못했습니다. 위치 설정과 권한을 확인해 주세요")
        for provider in registered:
            try:
                location = self.manager.getLastKnownLocation(provider)
                if location is not None:
                    self.listener.accept(location, cached=True)
            except Exception:
                LOG.exception("Cached location unavailable: %s", provider)

    def publish(self):
        state = self.engine.snapshot()
        intent = Intent(ACTION_STATUS).setPackage(PACKAGE)
        # Intent.putExtra is overloaded; a Python str can otherwise select char[].
        payload = autoclass("java.lang.String")(json.dumps(state, ensure_ascii=False, allow_nan=False))
        intent.putExtra("state", payload)
        self.context.sendBroadcast(intent)

    def notify(self):
        # Replace p4a's initial notification with a visible channel and a Stop action.
        context = self.context
        manager = cast("android.app.NotificationManager", context.getSystemService("notification"))
        channel = autoclass("android.app.NotificationChannel")("gps_collection", "GPS 전송", 2)
        manager.createNotificationChannel(channel)
        PendingIntent = autoclass("android.app.PendingIntent")
        flags = 0x04000000 | 0x08000000  # IMMUTABLE | UPDATE_CURRENT
        stop = PendingIntent.getBroadcast(context, 1, Intent(ACTION_STOP).setPackage(PACKAGE), flags)
        launch = context.getPackageManager().getLaunchIntentForPackage(PACKAGE)
        open_app = PendingIntent.getActivity(context, 0, launch, flags)
        builder = autoclass("android.app.Notification$Builder")(context, "gps_collection")
        builder.setContentTitle("Rubik GPS · 위치 수집 중")
        builder.setContentText(self.engine.snapshot()["status"])
        builder.setSmallIcon(context.getApplicationInfo().icon)
        builder.setContentIntent(open_app).setOngoing(True).setOnlyAlertOnce(True)
        builder.addAction(0, autoclass("java.lang.String")("전송 중지"), stop)
        manager.notify(1, builder.build())

    def close(self):
        try:
            self.manager.removeUpdates(self.listener)
        finally:
            if self.wake_lock is not None and self.wake_lock.isHeld():
                self.wake_lock.release()
            self.receiver.stop()
