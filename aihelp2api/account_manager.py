"""账号管理模块：加载、选择、刷新、自动补号。"""
import asyncio
import json
import random
from typing import Any, Dict, List, Optional

from config import (
    ACCOUNTS_FILE,
    ACCOUNT_MIN_THRESHOLD,
    AUTO_REGISTER_COUNT,
    DEFAULT_PASSWORD,
    FALLBACK_PASSWORD,
    FALLBACK_SESSION_TOKEN,
    FALLBACK_USERNAME,
    REGISTER_PREFIX,
)
from register import batch_register, login as oihelp_login_sync


def load_accounts() -> List[Dict[str, Any]]:
    """从 accounts.json 加载账号列表。"""
    if not ACCOUNTS_FILE.exists():
        return []
    try:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def save_accounts(accounts: List[Dict[str, Any]]) -> None:
    """保存账号列表到 accounts.json。"""
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2)


def pick_account() -> Dict[str, Any]:
    """从 accounts.json 随机选一个账号；若无则回退到环境变量配置。"""
    accounts = load_accounts()
    if accounts:
        return random.choice(accounts)
    return {
        "username": FALLBACK_USERNAME,
        "sessionToken": FALLBACK_SESSION_TOKEN,
        "password": FALLBACK_PASSWORD,
    }


async def refresh_account_session(account: Dict[str, Any]) -> Dict[str, Any]:
    """
    用账号的 username/password 重新登录，刷新 sessionToken 与余额,
    并回写到 accounts.json，返回更新后的账号 dict。
    """
    username = account.get("username")
    password = account.get("password") or DEFAULT_PASSWORD
    info = await asyncio.to_thread(oihelp_login_sync, username, password)
    account.update(info)
    # 回写到 accounts.json
    try:
        accounts = load_accounts()
        for i, a in enumerate(accounts):
            if a.get("username") == username:
                accounts[i] = account
                break
        else:
            accounts.append(account)
        save_accounts(accounts)
    except Exception:
        pass
    return account


async def ensure_session(account: Dict[str, Any]) -> Dict[str, Any]:
    """确保账号有可用 sessionToken; 缺失则自动登录补齐。"""
    if not account.get("sessionToken"):
        account = await refresh_account_session(account)
    return account


def check_and_auto_register() -> None:
    """
    检查账号数量，低于阈值时自动补号（同步调用，放后台线程）。
    """
    accounts = load_accounts()
    count = len(accounts)
    if count < ACCOUNT_MIN_THRESHOLD:
        print(f"📉 账号数量 ({count}) 低于阈值 ({ACCOUNT_MIN_THRESHOLD})，自动补号 {AUTO_REGISTER_COUNT} 个...")
        batch_register(AUTO_REGISTER_COUNT, REGISTER_PREFIX)
        print(f"✅ 自动补号完成")


async def auto_register_background() -> None:
    """后台定时检查并自动补号（启动时调用一次）。"""
    await asyncio.to_thread(check_and_auto_register)
