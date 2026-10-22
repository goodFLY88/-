[app]
title = ICVE刷课
package.name = icvetoolkit
package.domain = com.icve.tool

# 打包目录 = 仓库根目录(单一代码源,不再维护 APK工程/ 副本)
source.dir = .
# 注意:ttf 必须显式列出 —— buildozer 只打包 include_exts 里的扩展名,
# 漏掉 ttf 会导致 NotoSansSC.ttf 不进 APK,安卓端中文全部变豆腐块
source.include_exts = py,png,jpg,kv,atlas,ttf,json
source.exclude_dirs = tests, bin, .git, .github, .buildozer, __pycache__

version = 1.3

# 版本必须锁定:
# 1) KivyMD 2.0 是破坏性重构,删除了 1.x 的 OneLineListItem/TwoLineListItem 等
#    API,不锁版本 buildozer 会拉到 2.0.0,APK 启动即 ImportError 闪退;
#    kivy 锁 2.3.1 是为了与 kivymd 1.2.0 匹配。
# 2) requests/pycryptodome 锁大版本下限,避免未来破坏性变更。
requirements = python3, kivy==2.3.1, kivymd==1.2.0, requests>=2.28.0, pycryptodome>=3.18.0# 屏幕方向（portrait=竖屏）
orientation = portrait

# 安卓权限
android.permissions = INTERNET

# 目标安卓 SDK 版本（用较新稳定值，buildozer 会自动下载）
android.api = 33
android.ndk = 25b
android.minapi = 21
# 架构:默认只出 arm64-v8a,旧 32 位机型装不上;补上 armeabi-v7a
android.archs = arm64-v8a, armeabi-v7a

# 关闭调试（正式包）
android.debug = 0
android.release_artifact = apk
# release 包需要签名配置,取消注释并填入密钥库信息(debug 构建不受影响):
# android.keystore = my-release-key.keystore
# android.keyalias = mykey

# 全屏 / 状态栏
android.fullscreen = 0

# 窗口标题栏图标（后续放 icon.png 后启用）
# icon.filename = icon.png

[buildozer]
log_level = 2
warn_on_root = 1
