[app]
title = ICVE刷课
package.name = icvetoolkit
package.domain = com.icve.tool
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
source.exclude_dirs = tests, bin, .git
version = 1.0
# Pin a compatible Python target for Android
requirements = python3==3.11.9, kivy, kivymd, requests, pycryptodome, pyjnius
orientation = portrait
android.permissions = INTERNET
# 自动接受 SDK 许可证
android.accept_sdk_license = True
android.build_tools_version = 33.0.1
android.api = 33
android.ndk = 25b
android.minapi = 21
android.debug = 0
android.release_artifact = apk
android.fullscreen = 0
[buildozer]
log_level = 2
warn_on_root = 1
