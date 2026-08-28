#!/usr/bin/env python3
"""赤盘账号：邮箱密码 + Google / X OAuth。"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
USERS_PATH = DATA / "users.json"
LOCK = threading.Lock()
SESSION_TTL = 30 * 24 * 3600
DAILY_LIMIT = 30
PBKDF2_ROUNDS = 120_000
EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

PROVIDERS = {
    "google": {
        "label": "Google",
        "auth": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "userinfo": "https://www.googleapis.com/oauth2/v3/userinfo",
        "scope": "openid email profile",
        "id_env": "GOOGLE_CLIENT_ID",
        "secret_env": "GOOGLE_CLIENT_SECRET",
    },
    "x": {
        "label": "X",
        "auth": "https://twitter.com/i/oauth2/authorize",
        "token": "https://api.twitter.com/2/oauth2/token",
        "userinfo": "https://api.twitter.com/2/users/me?user.fields=name,username",
        "scope": "users.read tweet.read",
        "id_env": "X_CLIENT_ID",
        "secret_env": "X_CLIENT_SECRET",
    },
}


def _blank() -> dict:
    return {"users": {}, "sessions": {}, "oauth": {}, "quota": {}}


def load_store() -> dict:
    DATA.mkdir(parents=True, exist_ok=True)
    if not USERS_PATH.exists():
        return _blank()
    try:
        raw = json.loads(USERS_PATH.read_text(encoding="utf-8"))
        raw.setdefault("users", {})
        raw.setdefault("sessions", {})
        raw.setdefault("oauth", {})
        raw.setdefault("quota", {})
        return raw
    except Exception:
        return _blank()


def save_store(store: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = USERS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(USERS_PATH)


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ROUNDS)
    return f"{salt}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    if "$" not in stored:
        return False
    salt, _ = stored.split("$", 1)
    return hmac.compare_digest(hash_password(password, salt), stored)


def public_user(row: dict) -> dict:
    return {
        "id": row["id"],
        "email": row.get("email"),
        "name": row.get("name") or (row.get("email") or "用户").split("@")[0],
        "provider": row.get("provider") or "email",
    }


def providers_status() -> dict:
    out = {}
    for key, spec in PROVIDERS.items():
        out[key] = {
            "id": key,
            "label": spec["label"],
            "ready": bool(os.environ.get(spec["id_env"]) and os.environ.get(spec["secret_env"])),
        }
    return out


def shanghai_day(now: float | None = None) -> str:
    now = now or time.time()
    return time.strftime("%Y-%m-%d", time.gmtime(now + 8 * 3600))


def bump_quota(user_id: str, limit: int = DAILY_LIMIT) -> dict:
    day = shanghai_day()
    with LOCK:
        store = load_store()
        key = f"{day}:{user_id}"
        hits = int(store["quota"].get(key, 0))
        if hits >= limit:
            return {"ok": False, "code": "capped", "hits": hits, "limit": limit, "day": day}
        store["quota"][key] = hits + 1
        save_store(store)
        return {"ok": True, "hits": hits + 1, "limit": limit, "day": day}


def peek_quota(user_id: str, limit: int = DAILY_LIMIT) -> dict:
    day = shanghai_day()
    with LOCK:
        store = load_store()
        hits = int(store["quota"].get(f"{day}:{user_id}", 0))
    return {"hits": hits, "limit": limit, "day": day, "left": max(0, limit - hits)}


def create_session(store: dict, user_id: str) -> str:
    dead = [sid for sid, sess in store["sessions"].items() if time.time() - sess.get("at", 0) > SESSION_TTL]
    for sid in dead:
        store["sessions"].pop(sid, None)
    token = secrets.token_urlsafe(32)
    store["sessions"][token] = {"userId": user_id, "at": time.time()}
    return token


def user_from_cookie(header: str | None) -> dict | None:
    token = cookie_value(header, "chipan_sid")
    if not token:
        return None
    with LOCK:
        store = load_store()
        sess = store["sessions"].get(token)
        if not sess:
            return None
        if time.time() - sess.get("at", 0) > SESSION_TTL:
            store["sessions"].pop(token, None)
            save_store(store)
            return None
        row = store["users"].get(sess["userId"])
        return public_user(row) if row else None


def cookie_value(header: str | None, name: str) -> str | None:
    if not header:
        return None
    for part in header.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        if key.strip() == name:
            return value.strip()
    return None


def session_cookie(token: str | None) -> str:
    if not token:
        return "chipan_sid=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
    return f"chipan_sid={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_TTL}"


def register_email(email: str, password: str, name: str = "") -> tuple[dict | None, str | None, str | None]:
    email = email.strip().lower()
    password = password.strip()
    name = name.strip()[:40]
    if not EMAIL_RE.match(email):
        return None, None, "邮箱格式不对"
    if len(password) < 8:
        return None, None, "密码至少 8 位"
    with LOCK:
        store = load_store()
        for row in store["users"].values():
            if row.get("email") == email:
                return None, None, "这个邮箱已经注册"
        user_id = "u_" + secrets.token_hex(8)
        row = {
            "id": user_id,
            "email": email,
            "name": name or email.split("@")[0],
            "provider": "email",
            "password": hash_password(password),
            "createdAt": time.time(),
        }
        store["users"][user_id] = row
        token = create_session(store, user_id)
        save_store(store)
    return public_user(row), token, None


def login_email(email: str, password: str) -> tuple[dict | None, str | None, str | None]:
    email = email.strip().lower()
    password = password.strip()
    with LOCK:
        store = load_store()
        row = next((u for u in store["users"].values() if u.get("email") == email and u.get("provider") == "email"), None)
        if not row or not check_password(password, row.get("password") or ""):
            return None, None, "邮箱或密码不对"
        token = create_session(store, row["id"])
        save_store(store)
    return public_user(row), token, None


def logout(header: str | None) -> None:
    token = cookie_value(header, "chipan_sid")
    if not token:
        return
    with LOCK:
        store = load_store()
        store["sessions"].pop(token, None)
        save_store(store)


def start_oauth(provider: str, origin: str) -> tuple[str | None, str | None]:
    spec = PROVIDERS.get(provider)
    if not spec:
        return None, "不支持这个登录方式"
    client_id = os.environ.get(spec["id_env"], "")
    secret = os.environ.get(spec["secret_env"], "")
    if not client_id or not secret:
        return None, "社交登录尚未配置密钥，请先用邮箱"
    state = secrets.token_urlsafe(24)
    redirect = f"{origin.rstrip('/')}/api/auth/callback/{provider}"
    with LOCK:
        store = load_store()
        store["oauth"][state] = {"provider": provider, "at": time.time(), "redirect": redirect}
        save_store(store)
    query = {
        "client_id": client_id,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": spec["scope"],
        "state": state,
    }
    if provider == "google":
        query["access_type"] = "online"
        query["prompt"] = "select_account"
    if provider == "x":
        query["code_challenge"] = "plain"
        query["code_challenge_method"] = "plain"
    return spec["auth"] + "?" + urllib.parse.urlencode(query), None


def finish_oauth(provider: str, code: str, state: str) -> tuple[dict | None, str | None, str | None]:
    spec = PROVIDERS.get(provider)
    if not spec:
        return None, None, "不支持这个登录方式"
    with LOCK:
        store = load_store()
        pending = store["oauth"].pop(state, None)
        save_store(store)
    if not pending or pending.get("provider") != provider:
        return None, None, "登录状态已过期，请再点一次"
    if time.time() - pending.get("at", 0) > 600:
        return None, None, "登录状态已过期，请再点一次"
    client_id = os.environ.get(spec["id_env"], "")
    secret = os.environ.get(spec["secret_env"], "")
    token_body = {
        "client_id": client_id,
        "client_secret": secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": pending["redirect"],
    }
    req = urllib.request.Request(
        spec["token"],
        data=urllib.parse.urlencode(token_body).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "chipan-auth"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as res:
            token = json.loads(res.read().decode("utf-8"))
    except Exception:
        return None, None, "社交登录没有换到令牌"
    access = token.get("access_token")
    if not access:
        return None, None, "社交登录没有换到令牌"
    info_req = urllib.request.Request(
        spec["userinfo"],
        headers={"Authorization": f"Bearer {access}", "User-Agent": "chipan-auth"},
    )
    try:
        with urllib.request.urlopen(info_req, timeout=12) as res:
            info = json.loads(res.read().decode("utf-8"))
    except Exception:
        return None, None, "没有读到社交账号资料"
    if provider == "google":
        email = (info.get("email") or "").lower()
        name = info.get("name") or email.split("@")[0]
        ext_id = info.get("sub") or email
    else:
        data = info.get("data") or info
        name = data.get("name") or data.get("username") or "X用户"
        email = f"{data.get('username') or data.get('id')}@x.local"
        ext_id = str(data.get("id") or name)
    if not ext_id:
        return None, None, "社交账号缺少标识"
    with LOCK:
        store = load_store()
        row = next(
            (u for u in store["users"].values() if u.get("provider") == provider and u.get("extId") == ext_id),
            None,
        )
        if not row and email:
            row = next((u for u in store["users"].values() if u.get("email") == email), None)
        if not row:
            user_id = "u_" + secrets.token_hex(8)
            row = {
                "id": user_id,
                "email": email or None,
                "name": name,
                "provider": provider,
                "extId": ext_id,
                "createdAt": time.time(),
            }
            store["users"][user_id] = row
        else:
            row["name"] = name or row.get("name")
            row["extId"] = ext_id
            row["provider"] = provider
        token_sid = create_session(store, row["id"])
        save_store(store)
    return public_user(row), token_sid, None
