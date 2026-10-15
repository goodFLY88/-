[app]
title = ICVE刷课
package.name = icvetoolkit
package.domain = com.icve.tool

source.dir = .
source.include_exts = py,png,jpg,kv,atlas
source.exclude_dirs = tests, bin, .git

version = 1.0

requirements = python3, kivy, kivymd, requests, pycryptodome
# 屏幕方向（portrait=竖屏）
orientation = portrait

# 安卓权限
android.permissions = INTERNET

# 目标安卓 SDK 版本（用较新稳定值，buildozer 会自动下载）
android.api = 33
android.ndk = 25b
android.minapi = 21

# 关闭调试（正式包）
android.debug = 0
android.release_artifact = apk

# 全屏 / 状态栏
android.fullscreen = 0

# 窗口标题栏图标（后续放 icon.png 后启用）
# icon.filename = icon.png

[buildozer]
log_level = 2
warn_on_root = 1
