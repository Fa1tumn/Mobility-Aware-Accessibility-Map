"""Contract tests for the Android permission bridge, without a device."""
from pathlib import Path
import importlib.util
import sys
import types
import unittest
from unittest.mock import patch


class PermissionBridgeTests(unittest.TestCase):
    def setUp(self):
        self.ui_queue=[]
        self.in_ui=False
        self.granted=set()
        self.requests=[]
        self.callbacks=[]
        self.sdk=35
        self.result=[]
        self.errors=[]
        class JavaString:
            def __init__(self,value): self.value=value
        self.JavaString=JavaString
        self.classes={'java.lang.String':JavaString}
        self.fine='android.permission.ACCESS_FINE_LOCATION'
        self.coarse='android.permission.ACCESS_COARSE_LOCATION'
        self.notification='android.permission.POST_NOTIFICATIONS'
        permissions=types.ModuleType('android.permissions')
        permissions.Permission=types.SimpleNamespace(ACCESS_FINE_LOCATION=self.fine,ACCESS_COARSE_LOCATION=self.coarse)
        permissions.check_permission=lambda name: name in self.granted
        def request(names,callback):
            self.assertTrue(self.in_ui,'Permissions requested outside Android UI thread')
            self.requests.append(names)
            self.callbacks.append(callback)
        permissions.request_permissions=request
        runnable=types.ModuleType('android.runnable')
        def ui_decorator(fn):
            def queued(*args,**kwargs): self.ui_queue.append(lambda:fn(*args,**kwargs))
            return queued
        runnable.run_on_ui_thread=ui_decorator
        jnius=types.ModuleType('jnius')
        jnius.PythonJavaClass=object
        jnius.java_method=lambda *args,**kwargs:lambda fn:fn
        jnius.cast=lambda name,value:value
        jnius.autoclass=lambda name:self.classes.get(name,types.SimpleNamespace(SDK_INT=self.sdk))
        broadcast=types.ModuleType('android.broadcast')
        broadcast.BroadcastReceiver=object
        self.modules=patch.dict(sys.modules,{'jnius':jnius,'android':types.ModuleType('android'),
            'android.permissions':permissions,'android.runnable':runnable,'android.broadcast':broadcast})
        self.modules.start()
        path=Path(__file__).resolve().parents[1]/'android_bridge.py'
        spec=importlib.util.spec_from_file_location('permission_bridge_under_test',path)
        self.bridge=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.bridge)

    def tearDown(self): self.modules.stop()

    def on_ui(self,callback):
        self.in_ui=True
        try: callback()
        finally: self.in_ui=False

    def start(self):
        self.bridge.request_start_permissions(self.result.append,self.errors.append)
        self.assertEqual(self.requests,[])
        self.on_ui(self.ui_queue.pop(0))

    def respond(self,granted=()):
        self.granted.update(granted)
        callback=self.callbacks.pop(0)
        self.on_ui(lambda:callback([],[]))

    def test_location_then_notifications_requested_on_ui_thread(self):
        self.start()
        self.assertEqual(self.requests,[[self.fine,self.coarse]])
        self.respond([self.fine,self.coarse])
        self.assertEqual(self.requests[-1],[self.notification])
        self.respond([self.notification])
        self.assertEqual(self.result,[True])
        self.assertEqual(self.errors,[])

    def test_approximate_location_is_not_accepted(self):
        self.start()
        self.respond([self.coarse])
        self.assertEqual(self.result,[False])
        self.assertEqual(len(self.requests),1)

    def test_denied_notifications_do_not_block_location_service(self):
        self.granted.update([self.fine,self.coarse])
        self.start()
        self.assertEqual(self.requests,[[self.notification]])
        self.respond()
        self.assertEqual(self.result,[True])

    def test_already_granted_permissions_finish_without_dialog(self):
        self.granted.update([self.fine,self.coarse,self.notification])
        self.start()
        self.assertEqual(self.requests,[])
        self.assertEqual(self.result,[True])

    def test_older_android_does_not_request_notification_permission(self):
        self.sdk=32
        self.granted.update([self.fine,self.coarse])
        self.start()
        self.assertEqual(self.requests,[])
        self.assertEqual(self.result,[True])

    def test_status_extra_uses_java_string_not_char_array(self):
        sent=[]
        java_string=self.JavaString
        class Intent:
            def __init__(self,action): self.action=action
            def setPackage(self,package): return self
            def putExtra(self,key,value):
                if not isinstance(value,java_string):
                    raise AssertionError('Python str can select the char[] overload')
                self.key,self.value=key,value
        self.bridge.Intent=Intent
        collector=object.__new__(self.bridge.AndroidCollector)
        collector.engine=types.SimpleNamespace(snapshot=lambda:{'running':True,'status':'수집 중'})
        collector.context=types.SimpleNamespace(sendBroadcast=sent.append)
        collector.publish()
        import json
        self.assertEqual(sent[0].key,'state')
        self.assertEqual(json.loads(sent[0].value.value)['status'],'수집 중')

    def test_notification_action_uses_java_char_sequence(self):
        calls=[]
        java_string=self.JavaString
        class Intent:
            def __init__(self,action): pass
            def setPackage(self,package): return self
        class Builder:
            def __init__(self,*args): pass
            def __getattr__(self,name): return lambda *args:self
            def addAction(self,icon,title,pending):
                if not isinstance(title,java_string):
                    raise AssertionError('Overloaded addAction requires a Java CharSequence')
                calls.append(title.value)
            def build(self): return object()
        self.bridge.Intent=Intent
        self.classes.update({
            'android.app.NotificationChannel':lambda *args:object(),
            'android.app.Notification$Builder':Builder,
            'android.app.PendingIntent':types.SimpleNamespace(getBroadcast=lambda *args:object(),getActivity=lambda *args:object()),
        })
        manager=types.SimpleNamespace(createNotificationChannel=lambda *args:None,notify=lambda *args:None)
        package_manager=types.SimpleNamespace(getLaunchIntentForPackage=lambda *args:object())
        context=types.SimpleNamespace(getSystemService=lambda *args:manager,getPackageManager=lambda:package_manager,
                                      getApplicationInfo=lambda:types.SimpleNamespace(icon=1))
        collector=object.__new__(self.bridge.AndroidCollector)
        collector.context=context
        collector.engine=types.SimpleNamespace(snapshot=lambda:{'status':'수집 중'})
        collector.notify()
        self.assertEqual(calls,['전송 중지'])

    def test_collector_registers_gps_and_network_and_marks_cache(self):
        calls, cached = [], []
        manager=types.SimpleNamespace(
            getAllProviders=lambda:types.SimpleNamespace(toArray=lambda:['gps','network','passive']),
            isProviderEnabled=lambda provider:True,
            requestLocationUpdates=lambda *args:calls.append(args),
            getLastKnownLocation=lambda provider:provider)
        wake_lock=types.SimpleNamespace(acquire=lambda:None)
        power=types.SimpleNamespace(newWakeLock=lambda *args:wake_lock)
        collector=object.__new__(self.bridge.AndroidCollector)
        collector.receiver=types.SimpleNamespace(start=lambda:None)
        collector.context=types.SimpleNamespace(getSystemService=lambda name:power)
        collector.manager=manager
        collector.engine=types.SimpleNamespace(message=lambda text:None)
        collector.listener=types.SimpleNamespace(accept=lambda location,**kwargs:cached.append((location,kwargs)))
        self.classes['android.os.Looper']=types.SimpleNamespace(getMainLooper=lambda:object())
        collector.start()
        self.assertEqual([(args[0],args[1]) for args in calls],[('gps',500),('network',1000)])
        self.assertEqual(cached,[('gps',{'cached':True}),('network',{'cached':True})])

    def test_network_absence_or_registration_failure_keeps_gps_collection(self):
        for available in (['gps'],['gps','network']):
            with self.subTest(available=available):
                calls=[]
                def request(provider,*args):
                    if provider=='network': raise RuntimeError('Network provider unavailable')
                    calls.append(provider)
                manager=types.SimpleNamespace(
                    getAllProviders=lambda:types.SimpleNamespace(toArray=lambda:available),
                    isProviderEnabled=lambda provider:True,requestLocationUpdates=request,
                    getLastKnownLocation=lambda provider:None)
                power=types.SimpleNamespace(newWakeLock=lambda *args:types.SimpleNamespace(acquire=lambda:None))
                collector=object.__new__(self.bridge.AndroidCollector)
                collector.receiver=types.SimpleNamespace(start=lambda:None)
                collector.context=types.SimpleNamespace(getSystemService=lambda name:power)
                collector.manager=manager
                collector.engine=types.SimpleNamespace(message=lambda text:None)
                collector.listener=object()
                self.classes['android.os.Looper']=types.SimpleNamespace(getMainLooper=lambda:object())
                collector.start()
                self.assertEqual(calls,['gps'])

    def test_location_listener_preserves_source_accuracy_and_sensor_timestamp(self):
        submitted=[]
        listener=self.bridge.LocationListener(types.SimpleNamespace(submit=lambda *args,**kwargs:submitted.append((args,kwargs))))
        location=types.SimpleNamespace(hasAccuracy=lambda:True,getLatitude=lambda:37.5,getLongitude=lambda:127.5,
            getAccuracy=lambda:350,getElapsedRealtimeNanos=lambda:100_000_000_000,getProvider=lambda:'network')
        listener.onLocationChanged(location)
        fix=submitted[0][0][0]
        self.assertEqual((fix.latitude,fix.longitude,fix.accuracy_m,fix.captured_s),(37.5,127.5,350,100))
        self.assertEqual(submitted[0][1],{'source':'network','cached':False})


if __name__=='__main__': unittest.main()
