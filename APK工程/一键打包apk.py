#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ICVE 安卓一键打包（必须在 WSL/Ubuntu/Linux 终端里运行：python3 一键打包apk.py）"""
import os
import sys
import platform
import subprocess
import traceback

os.chdir(os.path.dirname(os.path.abspath(__file__)))


def pause():
    try:
        input("\n按回车键退出...")
    except Exception:
        pass


def run(cmd):
    print(">>", cmd, flush=True)
    subprocess.run(cmd, shell=True, check=True)


if __name__ == "__main__":
    # 环境检测：Windows 下不能直接打 APK
    if platform.system() != "Linux":
        print("=" * 50)
        print("  不能在这里直接打包！")
        print("=" * 50)
        print("这个脚本会调用 Linux 的 apt 安装安卓 SDK，")
        print("请在 WSL 里运行：")
        print("  1. PowerShell(管理员) 运行 wsl --install -d Ubuntu")
        print("  2. 进入 WSL 后再执行 python3 一键打包apk.py")
        print("=" * 50)
        pause()
        sys.exit(1)

    try:
        print("=" * 40)
        print("  ICVE 安卓一键打包")
        print("=" * 40)

        print("[1/3] 安装系统依赖（会提示输入密码）...", flush=True)
        run("sudo apt update")
        run("sudo apt install -y git zip unzip openjdk-17-jdk python3-pip autoconf "
            "libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev "
            "libffi-dev libssl-dev")

        print("[2/3] 安装 buildozer...", flush=True)
        run("pip3 install --user --upgrade buildozer")
        os.environ["PATH"] = os.path.expanduser("~/.local/bin") + os.pathsep + os.environ.get("PATH", "")

        print("[3/3] 开始打包 APK（首次下载 SDK/NDK 约 1GB，耐心等）...", flush=True)
        run("buildozer -v android debug")

        print("\n" + "=" * 40)
        print("  完成！APK 在 bin/ 目录：")
        if os.path.isdir("bin"):
            for f in os.listdir("bin"):
                if f.endswith(".apk"):
                    print("   bin/" + f)
        print("=" * 40)
    except Exception as e:
        print("\n[出错了] 详细信息：", flush=True)
        traceback.print_exc()
        print("\n如果是 'sudo: command not found' / 'apt: not found'，说明你在")
        print("Windows 里双击了——请改到 WSL 终端里运行本脚本。")
    finally:
        pause()
