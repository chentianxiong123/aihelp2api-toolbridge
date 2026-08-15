"""
OIHelp 批量注册 (Python 版)
注册新账号并保存到 accounts.json。
依赖: pip install requests
"""

import json
import os
import random
import string
import time
import urllib3

import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API_BASE = "https://www.oihelp.cn"
ACCOUNTS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "accounts.json"
)
DEFAULT_PASSWORD = "oihelp2024"
DEFAULT_PREFIX = "oi_"
REGISTER_COUNT = 10
CONCURRENCY = 3
TIMEOUT = 15

HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://www.oihelp.cn",
    "Referer": "https://www.oihelp.cn/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/149.0.0.0 Safari/537.36"
    ),
}


def load_accounts():
    if not os.path.exists(ACCOUNTS_FILE):
        return []
    try:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def save_accounts(accounts):
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2)


def random_name(prefix=DEFAULT_PREFIX):
    chars = string.ascii_lowercase + string.digits
    return prefix + "".join(random.choice(chars) for _ in range(8))


def register(username, password=DEFAULT_PASSWORD):
    """注册单个账号，成功返回账号 dict，失败抛异常。"""
    resp = requests.post(
        f"{API_BASE}/api/register",
        headers=HEADERS,
        json={"username": username, "password": password},
        verify=False,
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:80]}")
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(data.get("error") or "注册失败")
    acct = {
        "username": username,
        "password": password,
        "points": data.get("points", 0),
        "createdAt": int(time.time() * 1000),
    }
    # 注册成功后立即登录，补齐 sessionToken 和余额
    try:
        login_info = login(username, password)
        acct.update(login_info)
    except Exception as e:
        # 登录失败不影响注册结果，仅记录原因
        acct["loginError"] = str(e)
    return acct


def login(username, password=DEFAULT_PASSWORD):
    """
    用户名密码登录，返回 {sessionToken, tokenLimit, isAdmin, balance}。
    登录响应示例:
      {"success":true,"username":"ttff33","sessionToken":"mqmdi4zxa3fxhix7zh9",
       "isAdmin":false,"tokenLimit":200000,"appearance":{...}}
    其中 tokenLimit 即为账户剩余额度(余额)。
    """
    resp = requests.post(
        f"{API_BASE}/api/login",
        headers=HEADERS,
        json={"username": username, "password": password},
        verify=False,
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"登录 HTTP {resp.status_code}: {resp.text[:80]}")
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(data.get("error") or "登录失败")
    return {
        "sessionToken": data.get("sessionToken"),
        "tokenLimit": data.get("tokenLimit"),
        "isAdmin": data.get("isAdmin", False),
        "balance": data.get("tokenLimit"),  # tokenLimit 即余额
    }


def batch_register(count=REGISTER_COUNT, prefix=DEFAULT_PREFIX):
    """批量注册账号，返回 (成功数, 失败数)。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    accounts = load_accounts()
    success = fail = 0

    def task():
        uname = random_name(prefix)
        try:
            return "ok", uname, register(uname)
        except Exception as e:
            return "fail", uname, str(e)

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = [pool.submit(task) for _ in range(count)]
        for fut in as_completed(futures):
            kind, uname, payload = fut.result()
            if kind == "ok":
                accounts.append(payload)
                success += 1
                token = (payload.get("sessionToken") or "")[:10]
                balance = payload.get("balance", payload.get("points", 0))
                print(f"  ✅ {uname}  (余额: {balance}, token: {token}...)")
            else:
                fail += 1
                print(f"  ❌ {uname}: {payload}")

    save_accounts(accounts)
    print(f"\n📊 结果: ✅ {success} 成功  ❌ {fail} 失败  📁 共 {len(accounts)} 个账号")
    return success, fail


def get_random_account():
    accounts = load_accounts()
    return random.choice(accounts) if accounts else None


def login_all_accounts():
    """
    对 accounts.json 中所有账号重新登录，刷新 sessionToken 和余额。
    用于给旧账号补字段或 token 过期后刷新。
    """
    accounts = load_accounts()
    if not accounts:
        print("没有账号可登录。")
        return
    ok = fail = 0
    for a in accounts:
        try:
            info = login(a["username"], a["password"])
            a.update(info)
            ok += 1
            print(f"  ✅ {a['username']}  (余额: {info['balance']})")
        except Exception as e:
            fail += 1
            print(f"  ❌ {a.get('username')}: {e}")
    save_accounts(accounts)
    print(f"\n📊 结果: ✅ {ok} 成功  ❌ {fail} 失败  📁 共 {len(accounts)} 个账号")


if __name__ == "__main__":
    batch_register()
