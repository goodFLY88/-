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
#    kivy 锁 2.3.1 是为了与 kivymd 1.x 匹配。
# 2) kivymd 只能锁 1.0.2:1.1.1/1.2.0 官方只发了源码包(tar.gz)没有 wheel,
#    而 p4a 装纯 Python 包时用 --only-binary=:all: + android 平台过滤,
#    源码包直接被跳过(实测报错:Could not find a version that satisfies
#    kivymd==1.2.0, from versions: ..., 1.0.1, 1.0.2, 2.0.0)。
#    1.0.2 是最后一个有 wheel 的 1.x 版本,API 与本项目兼容(冒烟测试通过)。
# 3) 不装 pycryptodome：官方只有桌面平台 wheel，p4a 的 --only-binary +
#    android 平台过滤下解析不到（实测构建失败）。改用零依赖纯 Python
#    AES 兼容层 aes_compat.py（zjy_client.py 内 try/except 自动回退）。
# 4) urllib3/certifi/idna/chardet 显式列出：requests 的依赖。
#    p4a 的依赖自动解析(dry-run)会因 kivymd 依赖 kivy(只有 NDK 编译产物,
#    PyPI 无 android wheel)而失败,失败后回退原始列表且正式安装用 --no-deps,
#    requests 的传递依赖不会进列表 → 运行时 ImportError,必须显式写全。
#    这些都是 py3-none-any wheel,only-binary 下可装。
# 5) requests 锁大版本下限,避免未来破坏性变更。
requirements = python3, kivy==2.3.1, kivymd==1.0.2, requests>=2.28.0, urllib3, certifi, idna, chardet
# 屏幕方向（portrait=竖屏）
orientation = portrait

# 安卓权限
android.permissions = INTERNET

# 目标安卓 SDK 版本。原设 37（Android 17），但 Android 17 目前仍是 preview
# （Cinnamon Bun），sdkmanager 仓库里没有 platforms;android-37 平台包，
# 构建必失败（实测 6 次 attempt 全挂在 Failed to find package platforms;android-37）。
# 退 36（Android 16 稳定版，Play 2026-08 起的目标版本要求线）：
# targetSdk 36 在安卓 17 真机上完全兼容运行（向下兼容是标准场景），
# 且拿到 16KB 内存页支持才是安卓 17 不崩的关键（见下方 NDK 28c）。
android.api = 36
# NDK 必须 r27+，r28c 起完整支持 16KB 内存页对齐：
# 安卓 15+ 新机（含全部安卓 17 机型）默认 16KB 页，旧 NDK 编出的 .so
# 是 4KB 对齐，在这些设备上 dlopen 直接失败 → 启动闪退。
# （曾用 NDK 25b + api33，安卓 17 上必崩；27b 是无效版本号，NDK 命名是
#  r27c/r28c 这种格式）
android.ndk = 28c
# p4a 用 develop 分支：16KB 对齐修复与 api 37 支持先进 develop
# （稳定分支 lag；社区验证配置：api36/ndk28c/arm64 + p4a develop 可解 16KB 问题）
p4a.branch = develop
# 显式锁 Python 3.13：镜像默认 3.14 会踩 ensurepip 旧 pip 不兼容的坑
p4a.python_version = 3.13
# 架构：安卓 17 机型均为 arm64，且 Google 已在新系统陆续移除 32 位支持。
# 只出 arm64-v8a：单架构 CI 构建时间减半（双架构约 40 分钟易超时），
# 包体也小一半。16KB 对齐的 .so 在 4KB 页旧机上仍可运行（向后兼容）。
android.archs = arm64-v8a
# 最低支持 Android 5.0（16KB 对齐 .so 在 4KB 页设备上正常跑）
android.minapi = 21

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
