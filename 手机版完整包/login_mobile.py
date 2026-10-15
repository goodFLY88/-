#!/usr/bin/env python3
"""手机(Termux)极简登录脚本 —— 不走滑块，浏览器回调或手动粘贴 Token。

用法:
    python login_mobile.py
登录成功后账号自动保存到 accounts.json，之后直接 `python main.py` 选编号即可。
"""
import sys
from http.server import HTTPServer

try:
    from zjy_client import SSO_BASE, ZjyClient
    from auth import (CALLBACK_HOST, CALLBACK_PORT, CALLBACK_URL,
                      CallbackHandler, _exchange_token)
    from accounts import save_account
    import auth
except Exception as e:
    print("模块导入失败，请确认本脚本与 ICVE 业务模块放在同一目录：", e)
    sys.exit(1)

TIMEOUT = 300  # 等待回调秒数


def wait_callback():
    """方式1：打印 SSO 链接，本地 9527 端口等浏览器登录回调。"""
    auth._captured_token = None
    sso_url = f"{SSO_BASE}/h5/?mode=simple&source=15&redirect={CALLBACK_URL}#/login"
    print("\n1) 复制下面链接，用手机浏览器打开并登录：\n")
    print("   " + sso_url + "\n")
    print("2) 登录成功后会自动跳转回本程序（页面提示成功即可）。")
    print(f"   本程序在 {TIMEOUT} 秒内等待，期间请保持 Termux 运行…\n")
    try:
        server = HTTPServer((CALLBACK_HOST, CALLBACK_PORT), CallbackHandler)
    except OSError as e:
        print("启动回调失败（端口 9527 是否被占用？）：", e)
        return None
    server.timeout = 1
    for _ in range(TIMEOUT):
        server.handle_request()
        if auth._captured_token:
            break
    server.server_close()
    tok = auth._captured_token
    if not tok:
        print("登录超时，未捕获到 Token。")
        return None
    return _exchange_token(tok)


def manual_sso():
    """方式2：手动粘贴 sso_token（或带 token 的整条回调链接）。"""
    raw = input("粘贴 sso_token（或整条回调链接）：").strip()
    tok = raw
    if "token=" in raw:
        from urllib.parse import urlparse, parse_qs
        tok = (parse_qs(urlparse(raw).query).get("token") or [raw])[0]
    if not tok:
        print("Token 为空")
        return None
    return _exchange_token(tok)


def manual_bearer():
    """方式3：直接粘贴 bearer/access Token。"""
    tok = input("粘贴 bearer/access Token：").strip()
    if not tok:
        print("Token 为空")
        return None
    client = ZjyClient()
    if not client.apply_token(tok):
        print("Token 无效")
        return None
    save_account(client, "")
    return client


def main():
    print("=" * 46)
    print("   智慧职教 · 手机极简登录（无需滑块）")
    print("=" * 46)
    print("   1  浏览器回调登录（推荐）")
    print("   2  手动粘贴 sso_token")
    print("   3  手动粘贴 bearer_token")
    choice = input("选择 [1]: ").strip() or "1"
    if choice == "2":
        client = manual_sso()
    elif choice == "3":
        client = manual_bearer()
    else:
        client = wait_callback()
    if client:
        print("\n✅ 登录成功，账号已保存。现在运行：python main.py")
    else:
        print("\n❌ 登录未成功，可重新运行本脚本。")


if __name__ == "__main__":
    main()
