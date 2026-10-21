#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ICVE 安卓一键打包（在 WSL/Ubuntu 里运行：python3 一键打包apk.py）

优化版:打包目录即仓库根目录(buildozer.spec 同目录),不再需要 APK工程/ 副本。
"""
import os
import sys
import subprocess

# 切到本脚本所在目录(= 仓库根目录)
os.chdir(os.path.dirname(os.path.abspath(__file__)))


def run(cmd):
    print(">>", cmd, flush=True)
    subprocess.run(cmd, shell=True, check=True)


if __name__ == "__main__":
    try:
        print("=" * 40)
        print("  ICVE 安卓一键打包")
        print("=" * 40)

        print("[1/3] 安装系统依赖（需 sudo 密码）...", flush=True)
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
        for f in os.listdir("bin"):
            if f.endswith(".apk"):
                print("   bin/" + f)
        print("=" * 40)
    except subprocess.CalledProcessError as e:
        print("打包出错:", e, file=sys.stderr)
        sys.exit(1)
