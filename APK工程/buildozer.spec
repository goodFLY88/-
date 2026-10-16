[app]
title = ICVE刷课
package.name = icvetoolkit
package.domain = com.icve.tool
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf
source.exclude_dirs = tests, bin, .git
version = 1.0
requirements = python3, kivy, kivymd==1.2.0, requests, pycryptodome
orientation = portrait
android.permissions = INTERNET
android.accept_sdk_license = True
p4a.branch = v2026.05.09
android.api = 33
android.minapi = 21
android.debug = 0
android.release_artifact = apk
android.fullscreen = 0
[buildozer]
log_level = 2
warn_on_root = 0
