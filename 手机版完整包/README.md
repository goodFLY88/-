# ICVE 安卓 App 打包说明

## 一、在 Windows 上装 WSL（只需一次）
1. 以管理员打开 PowerShell，运行：`wsl --install -d Ubuntu`
2. 重启后按提示设 Ubuntu 用户名密码

## 二、一键打包
把整个 icve_android 文件夹放进 WSL（可放 `/home/你的用户名/icve_android`），然后：
```bash
cd ~/icve_android
python3 一键打包apk.py
```
- 脚本自动完成：装系统依赖 → 装 buildozer → 下载安卓 SDK/NDK → 出 APK
- 中途只需输一次 sudo 密码
- 首次会下载安卓 SDK/NDK（约 1GB+），耐心等
- 成功后 APK 在 `bin/` 目录，例如：
  `bin/icvetoolkit-1.0-arm64-v8a_debug.apk`

## 三、安装到手机
把 APK 传到手机（微信/QQ/数据线均可），点开安装（需允许"安装未知来源应用"）。

## 使用
1. 打开 App → 登录页复制链接到浏览器登录
2. 登录后复制浏览器地址栏网址，粘回 App 登录框
3. 登录成功自动进课程列表，点课程 → 刷课/答题/签到补签

## 注意
- 打包必须在 Linux/WSL，不能在 Windows 原生或手机上做
- 只装了 requests + pycryptodome，不打包滑块依赖
- 网络请求在后台线程，不会卡死界面
