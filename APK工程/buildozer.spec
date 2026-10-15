[app]
title = ICVE刷课
package.name = icvetoolkit
package.domain = com.icve.tool
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
source.exclude_dirs = tests, bin, .git
version = 1.0
# Pin a compatible Python target for Android
# Python 3.11 is the safest choice here; 3.14 is what is failing in the log
requirements = python3==3.11.9, kivy, kivymd, requests, pycryptodome, pyjnius
orientation = portrait
android.permissions = INTERNET
android.api = 33
android.ndk = 25b
android.minapi = 21
android.debug = 0
android.release_artifact = apk
android.fullscreen = 0
[buildozer]
log_level = 2
warn_on_root = 1
