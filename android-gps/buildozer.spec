[app]
title = Rubik GPS
package.name = rubikgps
package.domain = com.fa1tumn
source.dir = .
source.include_exts = py,otf,txt,png,xml
source.exclude_dirs = tests,bin,.venv,dist,__pycache__
version = 1.1.4
requirements = python3,kivy==2.3.1,pyjnius,android
orientation = portrait
fullscreen = 0
services = Gps:services/gps_service.py:foreground:foregroundServiceType=location
android.permissions = INTERNET,ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION,FOREGROUND_SERVICE,FOREGROUND_SERVICE_LOCATION,POST_NOTIFICATIONS,WAKE_LOCK
android.extra_manifest_xml = android/manifest.xml
android.api = 35
android.minapi = 26
android.ndk = 28c
android.ndk_api = 26
android.archs = arm64-v8a
android.allow_backup = False
android.accept_sdk_license = True
android.debug_artifact = apk
android.extra_manifest_application_arguments = android/application.xml
p4a.branch = develop
p4a.commit = 1c9a4b4f817847bd8505d972d1a0e6f965929a88

[buildozer]
log_level = 2
warn_on_root = 1
