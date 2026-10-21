"""账号管理模块:JSON 文件存储,支持多账号保存/切换/删除。

accounts.json 结构:
{
    "张三": {
        "token": "bearer_token",
        "ssoToken": "sso_token",
        "userName": "学号",
        "stuId": "学生ID",
        "nickName": "张三"
    }
}

安全与健壮性(优化版新增):
- 原子写入:先写临时文件再 os.replace,避免写一半损坏(断电/崩溃)
- 文件权限:非 Windows 下自动 chmod 600,仅本人可读(文件含登录 Token)
- 损坏备份:accounts.json 解析失败时自动备份为 accounts.json.bak-<时间戳>,
  再用空库启动,不会因一个坏文件丢掉全部账号
"""

import json
import os
import sys
import time
from typing import Optional

from utils import log

# 账号文件路径(与本模块同目录;打包成 exe 后取 exe 所在目录,避免写入临时解压目录)
if getattr(sys, "frozen", False):
    _BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ACCOUNTS_FILE = os.path.join(_BASE_DIR, "accounts.json")


def _restrict_permissions(path: str) -> None:
    """尽量把账号文件设为仅本人可读(Windows 上无 POSIX 权限,忽略失败)。"""
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def _atomic_write_json(path: str, data: dict) -> None:
    """原子写 JSON:临时文件 + os.replace,杜绝"写一半"的损坏文件。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    _restrict_permissions(path)


def load_accounts() -> dict:
    """加载全部已保存账号。

    :return: {nickname: account_info, ...}
    """
    try:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("accounts.json 顶层不是对象")
        return data
    except FileNotFoundError:
        return {}
    except Exception as e:
        # 文件损坏:备份后以空库启动,保住现场也保住可用性
        try:
            bak = f"{ACCOUNTS_FILE}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
            os.replace(ACCOUNTS_FILE, bak)
            log(f"账号文件已损坏,已备份为 {os.path.basename(bak)} ({e})", "ERROR")
        except Exception:
            log(f"加载账号文件异常: {e}", "ERROR")
        return {}


def save_accounts(accounts: dict) -> bool:
    """保存全部账号到 JSON 文件(原子写)。

    :return: True 表示保存成功
    """
    try:
        _atomic_write_json(ACCOUNTS_FILE, accounts)
        return True
    except Exception as e:
        log(f"保存账号文件异常: {e}", "ERROR")
        return False


def save_account(client, sso_token: str) -> bool:
    """登录成功后保存/更新单个账号。

    :param client: ZjyClient 实例(含 user_info / token / stu_id)
    :param sso_token: SSO 单点登录 token(用于 bearer 过期后刷新)
    :return: True 表示保存成功
    """
    if not client.user_info:
        log("保存账号失败: user_info 为空", "ERROR")
        return False

    accounts = load_accounts()
    nickname = client.user_info.get("nickName", "未知")
    existing = accounts.get(nickname, {})

    existing.update({
        "token": client.token,
        "ssoToken": sso_token,
        "userName": client.user_info.get("userName", ""),
        "stuId": client.stu_id or "",
        "nickName": nickname,
    })
    accounts[nickname] = existing
    return save_accounts(accounts)


def list_accounts() -> list:
    """返回 [(nickname, info), ...] 列表。"""
    return list(load_accounts().items())


def get_account(nickname: str) -> Optional[dict]:
    """按昵称获取单个账号信息。"""
    return load_accounts().get(nickname)


def delete_account(nickname: str) -> bool:
    """删除指定账号。

    :return: True 表示删除成功(存在且已删除)
    """
    accounts = load_accounts()
    if nickname not in accounts:
        return False
    del accounts[nickname]
    return save_accounts(accounts)
