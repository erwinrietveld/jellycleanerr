#!/usr/bin/env python3
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from http.cookiejar import CookieJar
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen, build_opener, HTTPCookieProcessor
from urllib.error import HTTPError, URLError
import tomllib

APP_PORT = int(os.getenv("PORT", "8282"))
APP_HOST = os.getenv("HOST", "0.0.0.0")
CONFIG_PATH = Path(
    os.getenv("JELLYCLEANERR_CONFIG")
    or os.getenv("SANITARR_CONFIG")
    or "/config/config.toml"
)
DB_PATH = Path(os.getenv("DB_PATH", "/data/jellycleanerr-gui.db"))
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "60"))
STATIC_DIR = Path(__file__).parent / "static"
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", str(60 * 60 * 24 * 7)))
SESSION_BROWSER_TTL_SECONDS = int(os.getenv("SESSION_BROWSER_TTL_SECONDS", str(60 * 60 * 12)))
MACHINE_API_KEYS = [part.strip() for part in os.getenv("JELLYCLEANERR_API_KEYS", "").split(",") if part.strip()]

cache_lock = threading.Lock()
cache_data = {"updated_at": 0.0, "payload": None, "error": None}
session_lock = threading.Lock()
sessions: dict[str, dict] = {}
DEFAULT_FORMULA1_TERMS = ["formula 1", "formula1", "formula one"]
ENABLE_FORMULA1_CATEGORY = os.getenv("ENABLE_FORMULA1_CATEGORY", "false").strip().lower() in {"1", "true", "yes", "on"}
DEFAULT_RETENTION = "60d"
DEFAULT_REMOVE_WATCHED_DAYS = 60
DEFAULT_REMOVE_UNWATCHED_DAYS = 365


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_duration(raw: str, default_days: int = 60) -> timedelta:
    if not raw:
        return timedelta(days=default_days)
    raw = raw.strip().lower()
    m = re.fullmatch(r"(\d+)\s*([smhdw])", raw)
    if not m:
        return timedelta(days=default_days)
    value = int(m.group(1))
    unit = m.group(2)
    if unit == "s":
        return timedelta(seconds=value)
    if unit == "m":
        return timedelta(minutes=value)
    if unit == "h":
        return timedelta(hours=value)
    if unit == "d":
        return timedelta(days=value)
    if unit == "w":
        return timedelta(weeks=value)
    return timedelta(days=default_days)


def read_config() -> dict:
    with CONFIG_PATH.open("rb") as f:
        cfg = tomllib.load(f)
    return cfg


def _toml_quote(value: str) -> str:
    escaped = str(value or "").replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _as_str_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return []


def _as_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _as_int(value, default: int, minimum: int = 1) -> int:
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        ivalue = default
    if ivalue < minimum:
        return minimum
    return ivalue


def _get_machine_api_token(headers) -> str:
    bearer = str(headers.get("Authorization") or "").strip()
    if bearer.lower().startswith("bearer "):
        return bearer[7:].strip()
    return str(headers.get("X-API-Key") or "").strip()


def _is_machine_api_authorized(headers) -> tuple[bool, str | None]:
    if not MACHINE_API_KEYS:
        return False, "machine api is disabled"
    token = _get_machine_api_token(headers)
    if not token:
        return False, "missing api key"
    for candidate in MACHINE_API_KEYS:
        if secrets.compare_digest(token, candidate):
            return True, None
    return False, "invalid api key"


def get_config_usernames(cfg: dict) -> list[str]:
    usernames = _as_str_list(cfg.get("usernames"))
    if usernames:
        return usernames
    fallback = str(cfg.get("username") or "").strip()
    return [fallback] if fallback else []


def get_primary_username(cfg: dict) -> str:
    usernames = get_config_usernames(cfg)
    return usernames[0] if usernames else str(cfg.get("username") or "").strip()


def config_for_ui(cfg: dict) -> dict:
    radarr_cfg = cfg.get("radarr", {}) or {}
    sonarr_cfg = cfg.get("sonarr", {}) or {}
    dls = cfg.get("download_clients", {}) or {}
    qbt = dls.get("qbittorrent", {}) or {}
    deluge = dls.get("deluge", {}) or {}
    general_cfg = cfg.get("general", {}) or {}
    watched_days = _as_int(
        general_cfg.get("remove_watched_days"),
        _as_int(parse_duration(str(radarr_cfg.get("retention_period") or DEFAULT_RETENTION)).days or DEFAULT_REMOVE_WATCHED_DAYS, DEFAULT_REMOVE_WATCHED_DAYS),
        1,
    )
    unwatched_days = _as_int(general_cfg.get("remove_unwatched_days"), DEFAULT_REMOVE_UNWATCHED_DAYS, 1)
    return {
        "username": get_primary_username(cfg),
        "usernames": get_config_usernames(cfg),
        "monitor_all_users": bool(cfg.get("monitor_all_users", False)),
        "monitor_all_libraries": bool(cfg.get("monitor_all_libraries", True)),
        "general": {
            "remove_watched_enabled": _as_bool(general_cfg.get("remove_watched_enabled"), True),
            "remove_watched_days": watched_days,
            "remove_unwatched_enabled": _as_bool(general_cfg.get("remove_unwatched_enabled"), False),
            "remove_unwatched_days": unwatched_days,
            "dry_run": _as_bool(general_cfg.get("dry_run"), True),
        },
        "jellyfin": {
            "base_url": str((cfg.get("jellyfin", {}) or {}).get("base_url") or ""),
            "api_key": str((cfg.get("jellyfin", {}) or {}).get("api_key") or ""),
            "library_ids": _as_str_list((cfg.get("jellyfin", {}) or {}).get("library_ids")),
        },
        "radarr": {
            "base_url": str(radarr_cfg.get("base_url") or ""),
            "api_key": str(radarr_cfg.get("api_key") or ""),
            "tags_to_keep": _as_str_list(radarr_cfg.get("tags_to_keep")),
            "retention_period": str(radarr_cfg.get("retention_period") or DEFAULT_RETENTION),
            "unmonitor_watched": bool(radarr_cfg.get("unmonitor_watched", False)),
        },
        "sonarr": {
            "base_url": str(sonarr_cfg.get("base_url") or ""),
            "api_key": str(sonarr_cfg.get("api_key") or ""),
            "tags_to_keep": _as_str_list(sonarr_cfg.get("tags_to_keep")),
            "retention_period": str(sonarr_cfg.get("retention_period") or DEFAULT_RETENTION),
            "unmonitor_watched": bool(sonarr_cfg.get("unmonitor_watched", False)),
        },
        "download_clients": {
            "qbittorrent": {
                "base_url": str(qbt.get("base_url") or ""),
                "username": str(qbt.get("username") or ""),
                "password": str(qbt.get("password") or ""),
            },
            "deluge": {
                "base_url": str(deluge.get("base_url") or ""),
                "password": str(deluge.get("password") or ""),
            },
        },
    }


def write_config(cfg: dict) -> None:
    ui = config_for_ui(cfg)
    monitor_all_users = bool(ui.get("monitor_all_users", False))
    monitor_all_libraries = bool(ui.get("monitor_all_libraries", True))
    usernames = ui.get("usernames") or []
    username = usernames[0] if usernames else str(ui.get("username") or "")
    if not monitor_all_users and not username:
        raise RuntimeError("at least one jellyfin username is required")

    jelly = ui["jellyfin"]
    radarr_cfg = ui["radarr"]
    sonarr_cfg = ui["sonarr"]
    qbt = (ui.get("download_clients") or {}).get("qbittorrent", {}) or {}
    deluge = (ui.get("download_clients") or {}).get("deluge", {}) or {}
    general_cfg = ui.get("general", {}) or {}

    tags_rad = ", ".join(_toml_quote(t) for t in _as_str_list(radarr_cfg.get("tags_to_keep")))
    tags_son = ", ".join(_toml_quote(t) for t in _as_str_list(sonarr_cfg.get("tags_to_keep")))
    users_raw = ", ".join(_toml_quote(u) for u in usernames)
    library_ids_raw = ", ".join(_toml_quote(x) for x in _as_str_list(jelly.get("library_ids")))
    remove_watched_enabled = _as_bool(general_cfg.get("remove_watched_enabled"), True)
    remove_watched_days = _as_int(general_cfg.get("remove_watched_days"), DEFAULT_REMOVE_WATCHED_DAYS, 1)
    remove_unwatched_enabled = _as_bool(general_cfg.get("remove_unwatched_enabled"), False)
    remove_unwatched_days = _as_int(general_cfg.get("remove_unwatched_days"), DEFAULT_REMOVE_UNWATCHED_DAYS, 1)
    dry_run = _as_bool(general_cfg.get("dry_run"), True)
    watched_retention = f"{remove_watched_days}d"

    lines = [
        f"username = {_toml_quote(username or '')}",
        f"usernames = [{users_raw}]",
        f"monitor_all_users = {'true' if monitor_all_users else 'false'}",
        f"monitor_all_libraries = {'true' if monitor_all_libraries else 'false'}",
        "",
        "[general]",
        f"remove_watched_enabled = {'true' if remove_watched_enabled else 'false'}",
        f"remove_watched_days = {remove_watched_days}",
        f"remove_unwatched_enabled = {'true' if remove_unwatched_enabled else 'false'}",
        f"remove_unwatched_days = {remove_unwatched_days}",
        f"dry_run = {'true' if dry_run else 'false'}",
        "",
        "[jellyfin]",
        f"base_url = {_toml_quote(jelly.get('base_url', ''))}",
        f"api_key = {_toml_quote(jelly.get('api_key', ''))}",
        f"library_ids = [{library_ids_raw}]",
        "",
        "[radarr]",
        f"base_url = {_toml_quote(radarr_cfg.get('base_url', ''))}",
        f"api_key = {_toml_quote(radarr_cfg.get('api_key', ''))}",
        f"tags_to_keep = [{tags_rad}]",
        f"retention_period = {_toml_quote(watched_retention)}",
        f"unmonitor_watched = {'true' if radarr_cfg.get('unmonitor_watched') else 'false'}",
        "",
        "[sonarr]",
        f"base_url = {_toml_quote(sonarr_cfg.get('base_url', ''))}",
        f"api_key = {_toml_quote(sonarr_cfg.get('api_key', ''))}",
        f"tags_to_keep = [{tags_son}]",
        f"retention_period = {_toml_quote(watched_retention)}",
        f"unmonitor_watched = {'true' if sonarr_cfg.get('unmonitor_watched') else 'false'}",
        "",
    ]

    if qbt.get("base_url") or qbt.get("username") or qbt.get("password"):
        lines.extend(
            [
                "[download_clients.qbittorrent]",
                f"base_url = {_toml_quote(qbt.get('base_url', ''))}",
                f"username = {_toml_quote(qbt.get('username', ''))}",
                f"password = {_toml_quote(qbt.get('password', ''))}",
                "",
            ]
        )
    if deluge.get("base_url") or deluge.get("password"):
        lines.extend(
            [
                "[download_clients.deluge]",
                f"base_url = {_toml_quote(deluge.get('base_url', ''))}",
                f"password = {_toml_quote(deluge.get('password', ''))}",
                "",
            ]
        )

    try:
        CONFIG_PATH.write_text("\n".join(lines), encoding="utf-8")
    except OSError as exc:
        if exc.errno == 30:
            raise RuntimeError(
                f"Config path '{CONFIG_PATH}' is read-only. Mount the file as read-write to save settings."
            ) from exc
        raise


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS keep_overrides (
                item_key TEXT PRIMARY KEY,
                keep INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS delete_history (
                item_key TEXT PRIMARY KEY,
                item_name TEXT NOT NULL,
                item_type TEXT NOT NULL,
                reason TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                deleted_at TEXT NOT NULL
            )
            """
        )
        con.commit()


def get_keep_overrides() -> dict[str, bool]:
    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute("SELECT item_key, keep FROM keep_overrides").fetchall()
    return {k: bool(v) for k, v in rows}


def set_keep_override(item_key: str, keep: bool) -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """
            INSERT INTO keep_overrides(item_key, keep, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(item_key) DO UPDATE SET
                keep = excluded.keep,
                updated_at = excluded.updated_at
            """,
            (item_key, 1 if keep else 0, utc_now().isoformat()),
        )
        con.commit()


def record_delete_event(item: dict) -> None:
    item_key = str(item.get("key") or "").strip()
    if not item_key:
        return
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """
            INSERT OR IGNORE INTO delete_history(item_key, item_name, item_type, reason, size_bytes, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                item_key,
                str(item.get("name") or ""),
                str(item.get("type") or ""),
                str(item.get("reason") or ""),
                int(item.get("sizeBytes") or 0),
                utc_now().isoformat(),
            ),
        )
        con.commit()


def get_delete_stats(days: int = 30) -> dict:
    today = utc_now().date()
    day_map = {}
    for i in range(max(days, 1)):
        day = today - timedelta(days=(days - 1 - i))
        day_map[day.isoformat()] = {"date": day.isoformat(), "count": 0, "sizeBytes": 0}

    with sqlite3.connect(DB_PATH) as con:
        total_row = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM delete_history"
        ).fetchone()
        recent_row = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM delete_history WHERE deleted_at >= ?",
            ((utc_now() - timedelta(days=days)).isoformat(),),
        ).fetchone()
        for d, count, size in con.execute(
            """
            SELECT substr(deleted_at, 1, 10) AS d, COUNT(*), COALESCE(SUM(size_bytes), 0)
            FROM delete_history
            WHERE deleted_at >= ?
            GROUP BY d
            ORDER BY d
            """,
            ((utc_now() - timedelta(days=days)).isoformat(),),
        ).fetchall():
            if d in day_map:
                day_map[d] = {"date": d, "count": int(count or 0), "sizeBytes": int(size or 0)}

    return {
        "totalCount": int((total_row or [0, 0])[0] or 0),
        "totalSizeBytes": int((total_row or [0, 0])[1] or 0),
        "recentCount": int((recent_row or [0, 0])[0] or 0),
        "recentSizeBytes": int((recent_row or [0, 0])[1] or 0),
        "daily": list(day_map.values()),
    }


def parse_date_only(raw: str | None) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def choose_bucket_granularity(start_dt: datetime, end_dt: datetime) -> str:
    span_days = max(int((end_dt - start_dt).days), 1)
    if span_days <= 90:
        return "day"
    if span_days <= 540:
        return "week"
    if span_days <= 3650:
        return "month"
    return "year"


def floor_bucket(dt: datetime, granularity: str) -> datetime:
    d = dt.astimezone(timezone.utc)
    if granularity == "day":
        return d.replace(hour=0, minute=0, second=0, microsecond=0)
    if granularity == "week":
        day = d - timedelta(days=d.weekday())
        return day.replace(hour=0, minute=0, second=0, microsecond=0)
    if granularity == "month":
        return d.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return d.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)


def step_bucket(dt: datetime, granularity: str) -> datetime:
    if granularity == "day":
        return dt + timedelta(days=1)
    if granularity == "week":
        return dt + timedelta(days=7)
    if granularity == "month":
        year = dt.year + (1 if dt.month == 12 else 0)
        month = 1 if dt.month == 12 else dt.month + 1
        return dt.replace(year=year, month=month, day=1)
    return dt.replace(year=dt.year + 1, month=1, day=1)


def http_json(
    url: str,
    headers: dict | None = None,
    timeout: int = 20,
    method: str = "GET",
    body: bytes | None = None,
) -> dict:
    req = Request(url, headers=headers or {}, method=method, data=body)
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def http_status(
    url: str,
    headers: dict | None = None,
    timeout: int = 20,
    method: str = "GET",
    body: bytes | None = None,
) -> int:
    req = Request(url, headers=headers or {}, method=method, data=body)
    with urlopen(req, timeout=timeout) as resp:
        _ = resp.read()
        return int(resp.status)


def test_jellyfin_connection(base_url: str, api_key: str) -> tuple[bool, str]:
    if not base_url or not api_key:
        return False, "missing base URL or API key"
    try:
        _ = jellyfin_get(base_url, api_key, "/System/Info/Public")
        return True, "connected"
    except Exception as exc:
        return False, str(exc)


def test_radarr_connection(base_url: str, api_key: str) -> tuple[bool, str]:
    if not base_url or not api_key:
        return False, "missing base URL or API key"
    try:
        _ = http_json(f"{base_url.rstrip('/')}/api/v3/system/status?apikey={api_key}")
        return True, "connected"
    except Exception as exc:
        return False, str(exc)


def test_sonarr_connection(base_url: str, api_key: str) -> tuple[bool, str]:
    if not base_url or not api_key:
        return False, "missing base URL or API key"
    try:
        _ = http_json(f"{base_url.rstrip('/')}/api/v3/system/status?apikey={api_key}")
        return True, "connected"
    except Exception as exc:
        return False, str(exc)


def test_qbittorrent_connection(base_url: str, username: str, password: str) -> tuple[bool, str]:
    if not base_url or not username:
        return False, "missing base URL or username"
    try:
        jar = CookieJar()
        opener = build_opener(HTTPCookieProcessor(jar))
        login_data = urlencode({"username": username, "password": password or ""}).encode("utf-8")
        req = Request(f"{base_url.rstrip('/')}/api/v2/auth/login", data=login_data, method="POST")
        raw = opener.open(req, timeout=20).read().decode("utf-8", errors="ignore").strip().lower()
        if "ok" in raw:
            return True, "connected"
        return False, raw or "login failed"
    except Exception as exc:
        return False, str(exc)


def test_deluge_connection(base_url: str, password: str) -> tuple[bool, str]:
    if not base_url or not password:
        return False, "missing base URL or password"
    try:
        body = json.dumps({"method": "auth.login", "params": [password], "id": 1}).encode("utf-8")
        payload = http_json(
            f"{base_url.rstrip('/')}/json",
            method="POST",
            headers={"Content-Type": "application/json"},
            body=body,
            timeout=20,
        )
        if payload.get("error"):
            return False, str(payload.get("error"))
        if payload.get("result") is True:
            return True, "connected"
        return False, "login failed"
    except Exception as exc:
        return False, str(exc)


def jellyfin_get(base_url: str, api_key: str, path: str, params: dict | None = None) -> dict:
    qs = urlencode(params or {})
    url = f"{base_url.rstrip('/')}{path}"
    if qs:
        url += f"?{qs}"
    return http_json(url, headers={"X-Emby-Token": api_key})


def jellyfin_authenticate(base_url: str, username: str, password: str) -> dict:
    url = f"{base_url.rstrip('/')}/Users/AuthenticateByName"
    body = json.dumps({"Username": username, "Pw": password}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": 'MediaBrowser Client="Jellycleanerr", Device="Web", DeviceId="jellycleanerr-web", Version="1.0.0"',
    }
    return http_json(url, headers=headers, method="POST", body=body)


def jellyfin_delete_item(base_url: str, api_key: str, item_id: str) -> None:
    url = f"{base_url.rstrip('/')}/Items/{item_id}"
    _ = http_status(url, headers={"X-Emby-Token": api_key}, method="DELETE")


def radarr_movies(base_url: str, api_key: str) -> dict[str, dict]:
    url = f"{base_url.rstrip('/')}/api/v3/movie?apikey={api_key}"
    items = http_json(url)
    by_tmdb = {}
    for m in items:
        tmdb = str(m.get("tmdbId") or "")
        if tmdb:
            by_tmdb[tmdb] = m
    return by_tmdb


def sonarr_series(base_url: str, api_key: str) -> dict[str, dict]:
    url = f"{base_url.rstrip('/')}/api/v3/series?apikey={api_key}"
    items = http_json(url)
    by_tvdb = {}
    for s in items:
        tvdb = str(s.get("tvdbId") or "")
        if tvdb:
            by_tvdb[tvdb] = s
    return by_tvdb


def radarr_delete_movie(base_url: str, api_key: str, movie_id: int) -> None:
    url = (
        f"{base_url.rstrip('/')}/api/v3/movie/{movie_id}"
        f"?deleteFiles=true&addImportExclusion=false&apikey={api_key}"
    )
    _ = http_status(url, method="DELETE")


def radarr_get_download_ids(base_url: str, api_key: str, movie_id: int) -> list[str]:
    url = (
        f"{base_url.rstrip('/')}/api/v3/history"
        f"?movieId={movie_id}&page=1&pageSize=50&sortDirection=descending&apikey={api_key}"
    )
    payload = http_json(url)
    ids = []
    for rec in payload.get("records", []):
        did = str(rec.get("downloadId") or "").strip()
        if did:
            ids.append(did)
    return ids


def sonarr_get_episodes(base_url: str, api_key: str, series_id: int) -> list[dict]:
    url = f"{base_url.rstrip('/')}/api/v3/episode?seriesId={series_id}&apikey={api_key}"
    return http_json(url)


def sonarr_update_episode(base_url: str, api_key: str, episode: dict) -> None:
    url = f"{base_url.rstrip('/')}/api/v3/episode?apikey={api_key}"
    body = json.dumps(episode).encode("utf-8")
    _ = http_status(url, method="PUT", body=body, headers={"Content-Type": "application/json"})


def sonarr_delete_episode_file(base_url: str, api_key: str, episode_file_id: int) -> None:
    url = f"{base_url.rstrip('/')}/api/v3/episodefile/{episode_file_id}?apikey={api_key}"
    _ = http_status(url, method="DELETE")


def sonarr_get_download_ids(base_url: str, api_key: str, series_id: int, episode_id: int) -> list[str]:
    url = (
        f"{base_url.rstrip('/')}/api/v3/history"
        f"?seriesId={series_id}&page=1&pageSize=100&sortDirection=descending&apikey={api_key}"
    )
    payload = http_json(url)
    ids = []
    for rec in payload.get("records", []):
        if int(rec.get("episodeId") or -1) != int(episode_id):
            continue
        did = str(rec.get("downloadId") or "").strip()
        if did:
            ids.append(did)
    return ids


def qbittorrent_delete_hashes(qbt_cfg: dict, hashes: list[str]) -> None:
    if not hashes:
        return
    base = str(qbt_cfg.get("base_url", "")).rstrip("/")
    user = str(qbt_cfg.get("username", ""))
    pw = str(qbt_cfg.get("password", ""))
    if not base or not user:
        return

    jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    login_data = urlencode({"username": user, "password": pw}).encode("utf-8")
    login_req = Request(f"{base}/api/v2/auth/login", data=login_data, method="POST")
    _ = opener.open(login_req, timeout=20).read()

    form = urlencode({"hashes": "|".join(hashes), "deleteFiles": "true"}).encode("utf-8")
    del_req = Request(f"{base}/api/v2/torrents/delete", data=form, method="POST")
    _ = opener.open(del_req, timeout=20).read()


def seerr_delete_by_tmdb(seerr_url: str, seerr_key: str, tmdb_id: str) -> bool:
    tmdb_id = str(tmdb_id or "").strip()
    if not tmdb_id:
        return False
    search_url = f"{seerr_url.rstrip('/')}/api/v1/search?query={tmdb_id}"
    payload = http_json(search_url, headers={"X-Api-Key": seerr_key})
    media_id = None
    for result in payload.get("results", []):
        info = result.get("mediaInfo") or {}
        if str(info.get("tmdbId") or "") == tmdb_id and info.get("id") is not None:
            media_id = int(info["id"])
            break
    if media_id is None:
        return False
    del_url = f"{seerr_url.rstrip('/')}/api/v1/media/{media_id}"
    _ = http_status(del_url, headers={"X-Api-Key": seerr_key}, method="DELETE")
    return True


def normalize_title(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def normalize_loose_text(value: str | None) -> str:
    if not value:
        return ""
    lowered = unicodedata.normalize("NFKD", str(value).lower())
    without_marks = "".join(ch for ch in lowered if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", without_marks)).strip()


def get_formula1_terms() -> list[str]:
    raw = os.getenv("FORMULA1_MATCH_TERMS", "")
    if not raw.strip():
        return DEFAULT_FORMULA1_TERMS
    terms = [normalize_loose_text(t) for t in raw.split(",") if normalize_loose_text(t)]
    return terms or DEFAULT_FORMULA1_TERMS


def is_formula1_item(item: dict) -> bool:
    text_bits = [
        str(item.get("SeriesName") or ""),
        str(item.get("Name") or ""),
        str(item.get("Path") or ""),
    ]
    haystack = normalize_loose_text(" ".join(text_bits))
    haystack_compact = re.sub(r"[^a-z0-9]+", "", haystack)
    for term in get_formula1_terms():
        term_compact = re.sub(r"[^a-z0-9]+", "", normalize_loose_text(term))
        if term and term in haystack:
            return True
        if term_compact and term_compact in haystack_compact:
            return True
    series_name = normalize_loose_text(str(item.get("SeriesName") or ""))
    return bool(re.search(r"\bf1\b", series_name))


def classify_category(item_type: str, item: dict) -> str:
    if item_type == "Movie":
        return "movies"
    if ENABLE_FORMULA1_CATEGORY and is_formula1_item(item):
        return "formula1"
    return "series"


def get_jellyfin_users(base_url: str, api_key: str) -> list[dict]:
    return jellyfin_get(base_url, api_key, "/Users")


def get_jellyfin_user(base_url: str, api_key: str, username: str) -> dict:
    users = get_jellyfin_users(base_url, api_key)
    uname = username.strip().lower()
    for u in users:
        if str(u.get("Name", "")).strip().lower() == uname:
            return u
    raise RuntimeError(f"Jellyfin user '{username}' not found")


def get_jellyfin_items(
    base_url: str,
    api_key: str,
    user_id: str,
    played: bool | None = None,
    parent_id: str | None = None,
) -> list[dict]:
    all_items = []
    start = 0
    limit = 200
    while True:
        params = {
            "Recursive": "true",
            "IncludeItemTypes": "Movie,Episode",
            "Fields": "Path,ProviderIds,PremiereDate,DateCreated,RunTimeTicks,MediaSources",
            "EnableUserData": "true",
            "SortBy": "DateCreated",
            "SortOrder": "Descending",
            "StartIndex": str(start),
            "Limit": str(limit),
        }
        if played is not None:
            params["IsPlayed"] = "true" if played else "false"
        if parent_id:
            params["ParentId"] = str(parent_id)
        payload = jellyfin_get(
            base_url,
            api_key,
            f"/Users/{user_id}/Items",
            params=params,
        )
        chunk = payload.get("Items", [])
        all_items.extend(chunk)
        total = int(payload.get("TotalRecordCount", len(all_items)))
        start += len(chunk)
        if not chunk or start >= total:
            break
    return all_items


def get_jellyfin_libraries(base_url: str, api_key: str, user_id: str) -> list[dict]:
    payload = jellyfin_get(base_url, api_key, f"/Users/{user_id}/Views")
    out = []
    for item in payload.get("Items", []):
        if str(item.get("Type") or "").strip().lower() != "collectionfolder":
            continue
        lid = str(item.get("Id") or "").strip()
        name = str(item.get("Name") or "").strip()
        if lid and name:
            out.append({"id": lid, "name": name})
    out.sort(key=lambda x: x["name"].lower())
    return out


def get_jellyfin_server_id(base_url: str, api_key: str) -> str:
    info = jellyfin_get(base_url, api_key, "/System/Info/Public")
    return str(info.get("Id") or "")


def media_key(item_type: str, provider_ids: dict, item_id: str) -> str:
    if item_type == "Movie":
        return f"movie:{provider_ids.get('Tmdb') or provider_ids.get('Imdb') or item_id}"
    if item_type == "Episode":
        return f"episode:{provider_ids.get('Tvdb') or item_id}"
    return f"item:{item_id}"


def calc_countdown(now: datetime, delete_at: datetime) -> str:
    diff = delete_at - now
    secs = int(diff.total_seconds())
    if secs <= 0:
        return "Due now"
    days = secs // 86400
    if days > 0:
        return f"{days}d"
    hours = (secs % 86400) // 3600
    if hours > 0:
        return f"{hours}h"
    mins = (secs % 3600) // 60
    return f"{max(mins, 1)}m"


def is_dry_run_enabled(cfg: dict | None = None) -> bool:
    config = cfg if isinstance(cfg, dict) else read_config()
    general = (config.get("general") or {}) if isinstance(config, dict) else {}
    return _as_bool(general.get("dry_run"), True)


def get_file_size_bytes(path: str | None) -> int:
    p = str(path or "").strip()
    if not p:
        return 0
    try:
        fp = Path(p)
        if fp.is_file():
            return int(fp.stat().st_size)
    except Exception:
        return 0
    return 0


def get_item_size_bytes(item: dict) -> int:
    direct = int(item.get("Size") or 0)
    if direct > 0:
        return direct
    sources = item.get("MediaSources") or []
    for src in sources:
        size = int((src or {}).get("Size") or 0)
        if size > 0:
            return size
    return get_file_size_bytes(item.get("Path"))


def parse_cookie_value(cookie_header: str | None, key: str) -> str:
    if not cookie_header:
        return ""
    for part in cookie_header.split(";"):
        raw = part.strip()
        if "=" not in raw:
            continue
        k, v = raw.split("=", 1)
        if k.strip() == key:
            return v.strip()
    return ""


def create_session(user: dict, ttl_seconds: int) -> str:
    sid = secrets.token_urlsafe(32)
    ttl = max(int(ttl_seconds or 0), 60)
    with session_lock:
        sessions[sid] = {
            "user": user,
            "ttl": ttl,
            "expires": time.time() + ttl,
        }
    return sid


def get_session(sid: str) -> dict | None:
    if not sid:
        return None
    with session_lock:
        entry = sessions.get(sid)
        if not entry:
            return None
        if entry["expires"] <= time.time():
            sessions.pop(sid, None)
            return None
        entry["expires"] = time.time() + max(int(entry.get("ttl") or SESSION_TTL_SECONDS), 60)
        return entry["user"]


def delete_session(sid: str) -> None:
    if not sid:
        return
    with session_lock:
        sessions.pop(sid, None)


def build_payload(fallback_usernames: list[str] | None = None) -> dict:
    cfg = read_config()
    jelly = cfg.get("jellyfin", {})
    radarr_cfg = cfg.get("radarr", {})
    sonarr_cfg = cfg.get("sonarr", {})

    jelly_base = jelly.get("base_url")
    jelly_key = jelly.get("api_key")
    selected_library_ids = _as_str_list(jelly.get("library_ids"))
    monitor_all_libraries = bool(cfg.get("monitor_all_libraries", True))
    monitor_all_users = bool(cfg.get("monitor_all_users", False))
    usernames = get_config_usernames(cfg)
    if not usernames and fallback_usernames:
        usernames = [u for u in (str(name).strip() for name in fallback_usernames) if u]
    if not jelly_base or not jelly_key:
        raise RuntimeError("Missing required Jellyfin credentials or monitored users in config")
    if not monitor_all_users and not usernames:
        raise RuntimeError("No monitored users configured")

    ui_cfg = config_for_ui(cfg)
    general_cfg = ui_cfg.get("general", {}) or {}
    remove_watched_enabled = _as_bool(general_cfg.get("remove_watched_enabled"), True)
    remove_watched_days = _as_int(general_cfg.get("remove_watched_days"), DEFAULT_REMOVE_WATCHED_DAYS, 1)
    remove_unwatched_enabled = _as_bool(general_cfg.get("remove_unwatched_enabled"), False)
    remove_unwatched_days = _as_int(general_cfg.get("remove_unwatched_days"), DEFAULT_REMOVE_UNWATCHED_DAYS, 1)
    dry_run = _as_bool(general_cfg.get("dry_run"), True)
    watched_retention = timedelta(days=remove_watched_days)
    unwatched_retention = timedelta(days=remove_unwatched_days)

    radarr_map = {}
    sonarr_map = {}
    sonarr_title_map = {}
    if radarr_cfg.get("base_url") and radarr_cfg.get("api_key"):
        radarr_map = radarr_movies(radarr_cfg["base_url"], radarr_cfg["api_key"])
    if sonarr_cfg.get("base_url") and sonarr_cfg.get("api_key"):
        sonarr_map = sonarr_series(sonarr_cfg["base_url"], sonarr_cfg["api_key"])
        for series in sonarr_map.values():
            n = normalize_title(series.get("title"))
            if n:
                sonarr_title_map[n] = series
    sonarr_has_data = len(sonarr_map) > 0 or len(sonarr_title_map) > 0

    server_id = get_jellyfin_server_id(jelly_base, jelly_key)
    users = get_jellyfin_users(jelly_base, jelly_key)
    by_name = {str(u.get("Name", "")).strip().lower(): u for u in users}
    if monitor_all_users:
        selected = users
    else:
        selected = []
        for uname in usernames:
            user = by_name.get(uname.strip().lower())
            if user is None:
                raise RuntimeError(f"Jellyfin user '{uname}' not found")
            selected.append(user)

    # Aggregate media for all selected users:
    # - watched uses the first watch date across monitored users
    # - unwatched uses item created/premiere date as idle baseline
    media_by_key: dict[str, dict] = {}
    now = utc_now()
    for user in selected:
        user_name = str(user.get("Name") or "")
        user_id = str(user.get("Id") or "")
        user_items = []
        if monitor_all_libraries:
            user_items = get_jellyfin_items(jelly_base, jelly_key, user_id, played=None)
        elif selected_library_ids:
            for library_id in selected_library_ids:
                user_items.extend(
                    get_jellyfin_items(
                        jelly_base,
                        jelly_key,
                        user_id,
                        played=None,
                        parent_id=library_id,
                    )
                )
        else:
            user_items = []
        for it in user_items:
            itype = it.get("Type")
            if itype not in {"Movie", "Episode"}:
                continue
            provider_ids = it.get("ProviderIds", {}) or {}
            key = media_key(itype, provider_ids, str(it.get("Id")))
            # Idle cleanup should be based on when media was added to the library,
            # not the original release/premiere date.
            created_at = parse_datetime(it.get("DateCreated")) or now
            user_data = it.get("UserData") or {}
            watched_at = parse_datetime(user_data.get("LastPlayedDate"))
            played = bool(user_data.get("Played"))
            in_progress = (not played) and int(user_data.get("PlaybackPositionTicks") or 0) > 0
            packed = media_by_key.get(key)
            if packed is None:
                packed = {
                    "item": it,
                    "createdAt": created_at,
                    "firstWatchedAt": None,
                    "watchers": set(),
                    "inProgress": False,
                }
                media_by_key[key] = packed
            else:
                if created_at < packed["createdAt"]:
                    packed["createdAt"] = created_at
            if in_progress:
                packed["inProgress"] = True
            if played:
                packed["watchers"].add(user_name)
                if watched_at is None:
                    watched_at = created_at
                first = packed["firstWatchedAt"]
                if first is None or watched_at < first:
                    packed["firstWatchedAt"] = watched_at

    overrides = get_keep_overrides()
    items = []

    size_cache: dict[str, int] = {}
    for key, packed in media_by_key.items():
        if packed.get("inProgress"):
            continue
        it = packed["item"]
        created_at = packed["createdAt"]
        first_watched_at = packed["firstWatchedAt"]
        watchers = sorted([w for w in packed["watchers"] if w], key=lambda x: x.lower())
        is_watched = first_watched_at is not None
        reason = "watched" if is_watched else "idle_unwatched"
        if is_watched:
            if not remove_watched_enabled:
                continue
            basis_at = first_watched_at
            retention = watched_retention
            reason_label = "Watched"
            basis_label = "First watched"
        else:
            if not remove_unwatched_enabled:
                continue
            basis_at = created_at
            retention = unwatched_retention
            reason_label = "Unwatched (idle)"
            basis_label = "Added"
        itype = it.get("Type")
        provider_ids = it.get("ProviderIds", {}) or {}

        delete_at = basis_at + retention

        exists_in_arr = True
        arr_id = None
        arr_source = None

        if itype == "Movie":
            tmdb = str(provider_ids.get("Tmdb") or "")
            exists_in_arr = bool(tmdb and tmdb in radarr_map)
            if exists_in_arr:
                arr_id = radarr_map[tmdb].get("id")
                arr_source = "radarr"
        elif itype == "Episode":
            tvdb = str(provider_ids.get("Tvdb") or "")
            # Jellyfin episode provider IDs often do not map cleanly to Sonarr series IDs.
            # Treat episodes as in-arr unless Sonarr data is available and confirms they're missing.
            exists_in_arr = not sonarr_has_data
            if sonarr_has_data:
                exists_in_arr = bool(tvdb and tvdb in sonarr_map)
            if exists_in_arr:
                arr_id = sonarr_map.get(tvdb, {}).get("id")
                arr_source = "sonarr"
            else:
                series_name = str(it.get("SeriesName") or "")
                series_obj = sonarr_title_map.get(normalize_title(series_name))
                exists_in_arr = series_obj is not None
                if exists_in_arr:
                    arr_id = series_obj.get("id")
                    arr_source = "sonarr"

        keep = overrides.get(key, False)

        if keep:
            status = "kept"
        elif now >= delete_at:
            status = "due"
        else:
            status = "pending"
        if status == "kept":
            queue_state = "kept"
        elif status == "due":
            queue_state = "due"
        elif reason == "watched":
            queue_state = "pending_watched"
        else:
            queue_state = "pending_idle"

        poster_id = it.get("SeriesId") if itype == "Episode" and it.get("SeriesId") else it.get("Id")

        items.append(
            {
                "key": key,
                "jellyfinId": it.get("Id"),
                "name": it.get("Name"),
                "type": "movie" if itype == "Movie" else "episode",
                "seriesName": it.get("SeriesName"),
                "season": it.get("ParentIndexNumber"),
                "episode": it.get("IndexNumber"),
                "year": it.get("ProductionYear"),
                "path": it.get("Path"),
                "sizeBytes": size_cache.setdefault(str(it.get("Id") or ""), get_item_size_bytes(it)),
                "providerIds": provider_ids,
                "watchedBy": ", ".join(watchers),
                "watchedAt": (first_watched_at.isoformat() if first_watched_at else ""),
                "basisAt": basis_at.isoformat(),
                "basisLabel": basis_label,
                "reason": reason,
                "reasonLabel": reason_label,
                "deleteAt": delete_at.isoformat(),
                "countdown": calc_countdown(now, delete_at),
                "status": status,
                "queueState": queue_state,
                "keep": keep,
                "inArr": exists_in_arr,
                "arrSource": arr_source,
                "arrId": arr_id,
                "groupName": (it.get("SeriesName") or it.get("Name")) if itype == "Episode" else (it.get("Name") or ""),
                "category": classify_category(itype, it),
                "posterUrl": f"/api/image/{poster_id}",
                "detailsUrl": f"{jelly_base.rstrip('/')}/web/index.html#!/details?id={it.get('Id')}&serverId={server_id}",
            }
        )

    # Keep episodes grouped by series in "All" view so kept items remain visible
    # alongside their siblings instead of being pushed into a separate status block.
    order = {"due": 0, "pending": 1, "kept": 2}
    category_order = {"movies": 0, "series": 1, "formula1": 2}
    items.sort(
        key=lambda x: (
            category_order.get(x.get("category") or "", 99),
            normalize_title(x.get("groupName") or ""),
            int(x.get("season") or 0),
            int(x.get("episode") or 0),
            order.get(x["status"], 99),
            x["deleteAt"],
        )
    )

    summary = {
        "total": len(items),
        "due": sum(1 for i in items if i["status"] == "due"),
        "pending": sum(1 for i in items if i["status"] == "pending"),
        "pendingWatched": sum(1 for i in items if i["queueState"] == "pending_watched"),
        "pendingIdle": sum(1 for i in items if i["queueState"] == "pending_idle"),
        "kept": sum(1 for i in items if i["status"] == "kept"),
        "updatedAt": now.isoformat(),
    }

    return {
        "summary": summary,
        "settings": {
            "username": (usernames[0] if usernames else "all-users"),
            "usernames": [str(u.get("Name") or "") for u in selected],
            "monitor_all_users": monitor_all_users,
            "monitor_all_libraries": monitor_all_libraries,
            "formula1_enabled": ENABLE_FORMULA1_CATEGORY,
            "library_ids": selected_library_ids,
            "movieRetention": f"{remove_watched_days}d",
            "seriesRetention": f"{remove_watched_days}d",
            "general": {
                "remove_watched_enabled": remove_watched_enabled,
                "remove_watched_days": remove_watched_days,
                "remove_unwatched_enabled": remove_unwatched_enabled,
                "remove_unwatched_days": remove_unwatched_days,
                "dry_run": dry_run,
            },
        },
        "items": items,
    }


def delete_now(item_key: str) -> dict:
    cfg = read_config()

    payload = build_payload()
    target = next((i for i in payload["items"] if i.get("key") == item_key), None)
    if target is None:
        raise RuntimeError("item not found")

    jelly = cfg.get("jellyfin", {})
    radarr_cfg = cfg.get("radarr", {})
    sonarr_cfg = cfg.get("sonarr", {})
    qbt_cfg = ((cfg.get("download_clients") or {}).get("qbittorrent") or {})
    seerr_url = os.getenv("SEERR_URL", "").strip()
    seerr_key = os.getenv("SEERR_API_KEY", "").strip()

    result = {"item": item_key, "type": target.get("type"), "steps": []}

    def step(name: str, fn):
        try:
            out = fn()
            result["steps"].append({"name": name, "ok": True, "detail": out})
        except Exception as exc:
            result["steps"].append({"name": name, "ok": False, "error": str(exc)})

    # Remove from Jellyfin (library item)
    if jelly.get("base_url") and jelly.get("api_key") and target.get("jellyfinId"):
        step(
            "jellyfin_delete",
            lambda: jellyfin_delete_item(jelly["base_url"], jelly["api_key"], str(target["jellyfinId"])),
        )

    # Remove from arr + disk + qbt where possible
    if target.get("type") == "movie" and target.get("arrSource") == "radarr" and target.get("arrId") is not None:
        movie_id = int(target["arrId"])
        if radarr_cfg.get("base_url") and radarr_cfg.get("api_key"):
            step(
                "radarr_delete_movie",
                lambda: radarr_delete_movie(radarr_cfg["base_url"], radarr_cfg["api_key"], movie_id),
            )
            step(
                "qbittorrent_delete_torrent",
                lambda: qbittorrent_delete_hashes(
                    qbt_cfg,
                    radarr_get_download_ids(radarr_cfg["base_url"], radarr_cfg["api_key"], movie_id),
                ),
            )

    if target.get("type") == "episode" and target.get("arrSource") == "sonarr" and target.get("arrId") is not None:
        series_id = int(target["arrId"])
        season = int(target.get("season") or 0)
        episode_num = int(target.get("episode") or 0)
        if sonarr_cfg.get("base_url") and sonarr_cfg.get("api_key"):
            episodes = sonarr_get_episodes(sonarr_cfg["base_url"], sonarr_cfg["api_key"], series_id)
            matched = next(
                (e for e in episodes if int(e.get("seasonNumber") or -1) == season and int(e.get("episodeNumber") or -1) == episode_num),
                None,
            )
            if matched:
                if int(matched.get("episodeFileId") or 0) > 0:
                    step(
                        "sonarr_delete_episode_file",
                        lambda: sonarr_delete_episode_file(
                            sonarr_cfg["base_url"], sonarr_cfg["api_key"], int(matched["episodeFileId"])
                        ),
                    )
                matched["monitored"] = False
                step(
                    "sonarr_unmonitor_episode",
                    lambda: sonarr_update_episode(sonarr_cfg["base_url"], sonarr_cfg["api_key"], matched),
                )
                step(
                    "qbittorrent_delete_torrent",
                    lambda: qbittorrent_delete_hashes(
                        qbt_cfg,
                        sonarr_get_download_ids(
                            sonarr_cfg["base_url"], sonarr_cfg["api_key"], series_id, int(matched.get("id") or -1)
                        ),
                    ),
                )

    # Remove from Seerr/Jellyseerr (optional env wiring)
    tmdb_id = str((target.get("providerIds") or {}).get("Tmdb") or "")
    if seerr_url and seerr_key and tmdb_id:
        step("seerr_delete_media", lambda: seerr_delete_by_tmdb(seerr_url, seerr_key, tmdb_id))

    # Also keep override off after manual delete-now
    set_keep_override(item_key, False)
    deletion_step_names = {
        "jellyfin_delete",
        "radarr_delete_movie",
        "sonarr_delete_episode_file",
        "qbittorrent_delete_torrent",
        "seerr_delete_media",
    }
    deleted = any(s.get("ok") and s.get("name") in deletion_step_names for s in result.get("steps", []))
    if deleted:
        record_delete_event(target)
    return result


def bulk_action(keys: list[str], mode: str) -> dict:
    cleaned = [str(k).strip() for k in keys if str(k).strip()]
    if not cleaned:
        raise RuntimeError("no keys provided")

    out = {"mode": mode, "total": len(cleaned), "results": []}

    if mode == "keep":
        for key in cleaned:
            set_keep_override(key, True)
            out["results"].append({"key": key, "ok": True})
        return out

    if mode == "unkeep":
        for key in cleaned:
            set_keep_override(key, False)
            out["results"].append({"key": key, "ok": True})
        return out

    if mode == "delete":
        for key in cleaned:
            try:
                out["results"].append({"key": key, "ok": True, "result": delete_now(key)})
            except Exception as exc:
                out["results"].append({"key": key, "ok": False, "error": str(exc)})
        return out

    raise RuntimeError("unsupported mode")


def auto_delete_idle_media() -> dict:
    cfg = read_config()
    if is_dry_run_enabled(cfg):
        return {"total": 0, "deleted": 0, "errors": [], "dry_run": True}

    payload = build_payload()
    targets = [
        i for i in payload.get("items", [])
        if i.get("status") == "due"
        and i.get("reason") == "idle_unwatched"
        and not i.get("keep")
        and i.get("inArr")
    ]
    out = {"total": len(targets), "deleted": 0, "errors": []}
    for item in targets:
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        try:
            delete_now(key)
            out["deleted"] += 1
        except Exception as exc:
            out["errors"].append({"key": key, "error": str(exc)})
    return out


def get_payload(force: bool = False, fallback_usernames: list[str] | None = None) -> tuple[dict | None, str | None]:
    use_cache = not fallback_usernames
    if use_cache:
        with cache_lock:
            now = time.time()
            if not force and cache_data["payload"] and now - cache_data["updated_at"] < CACHE_TTL_SECONDS:
                return cache_data["payload"], cache_data["error"]

    payload = None
    err = None
    try:
        payload = build_payload(fallback_usernames=fallback_usernames)
    except Exception as exc:
        err = str(exc)

    if use_cache:
        with cache_lock:
            if payload is not None:
                cache_data["payload"] = payload
                cache_data["error"] = None
                cache_data["updated_at"] = time.time()
            else:
                cache_data["error"] = err
                cache_data["updated_at"] = time.time()
        return cache_data["payload"], cache_data["error"]

    return payload, err


def build_stats(
    force: bool = False,
    days: int = 30,
    start: str | None = None,
    end: str | None = None,
    all_data: bool = False,
    fallback_usernames: list[str] | None = None,
) -> tuple[dict | None, str | None]:
    payload, err = get_payload(force=force, fallback_usernames=fallback_usernames)
    if payload is None:
        return None, err
    items = payload.get("items", [])
    pending_items = [i for i in items if i.get("status") in {"pending", "due"}]
    kept_items = [i for i in items if i.get("status") == "kept"]
    due_items = [i for i in items if i.get("status") == "due"]
    delete_stats = get_delete_stats(days=30)
    now = utc_now()
    start_dt = parse_date_only(start) or (now - timedelta(days=days))
    end_dt = parse_date_only(end) or (now + timedelta(days=days))
    if all_data:
        candidates = []
        with sqlite3.connect(DB_PATH) as con:
            row = con.execute("SELECT MIN(deleted_at), MAX(deleted_at) FROM delete_history").fetchone()
        min_deleted = parse_datetime((row or ["", ""])[0] or "")
        max_deleted = parse_datetime((row or ["", ""])[1] or "")
        if min_deleted:
            candidates.append(min_deleted)
        if max_deleted:
            candidates.append(max_deleted)
        for item in pending_items:
            dt = parse_datetime(item.get("deleteAt"))
            if dt:
                candidates.append(dt)
        if candidates:
            start_dt = min(candidates)
            end_dt = max(candidates)
        else:
            start_dt = now - timedelta(days=30)
            end_dt = now + timedelta(days=30)
    if end_dt < start_dt:
        start_dt, end_dt = end_dt, start_dt
    start_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    granularity = choose_bucket_granularity(start_dt, end_dt)

    bucket_map: dict[str, dict] = {}
    cursor = floor_bucket(start_dt, granularity)
    last_bucket = floor_bucket(end_dt, granularity)
    while cursor <= last_bucket:
        key = cursor.date().isoformat()
        bucket_map[key] = {
            "bucketStart": key,
            "historicalCount": 0,
            "historicalSizeBytes": 0,
            "projectedCount": 0,
            "projectedSizeBytes": 0,
        }
        cursor = step_bucket(cursor, granularity)

    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute(
            "SELECT deleted_at, size_bytes FROM delete_history WHERE deleted_at >= ? AND deleted_at <= ? ORDER BY deleted_at",
            (start_dt.isoformat(), end_dt.isoformat()),
        ).fetchall()
    for deleted_at, size_bytes in rows:
        dt = parse_datetime(str(deleted_at))
        if dt is None:
            continue
        key = floor_bucket(dt, granularity).date().isoformat()
        if key not in bucket_map:
            continue
        bucket_map[key]["historicalCount"] += 1
        bucket_map[key]["historicalSizeBytes"] += int(size_bytes or 0)

    for item in pending_items:
        delete_at = parse_datetime(item.get("deleteAt"))
        if delete_at is None or delete_at < start_dt or delete_at > end_dt:
            continue
        key = floor_bucket(delete_at, granularity).date().isoformat()
        if key not in bucket_map:
            continue
        bucket_map[key]["projectedCount"] += 1
        bucket_map[key]["projectedSizeBytes"] += int(item.get("sizeBytes") or 0)

    timeline = []
    for bucket in bucket_map.values():
        bucket["totalCount"] = bucket["historicalCount"] + bucket["projectedCount"]
        bucket["totalSizeBytes"] = bucket["historicalSizeBytes"] + bucket["projectedSizeBytes"]
        timeline.append(bucket)

    out = {
        "current": {
            "pendingCount": len(pending_items),
            "pendingSizeBytes": sum(int(i.get("sizeBytes") or 0) for i in pending_items),
            "pendingWatchedCount": sum(1 for i in items if i.get("queueState") == "pending_watched"),
            "pendingWatchedSizeBytes": sum(int(i.get("sizeBytes") or 0) for i in items if i.get("queueState") == "pending_watched"),
            "pendingIdleCount": sum(1 for i in items if i.get("queueState") == "pending_idle"),
            "pendingIdleSizeBytes": sum(int(i.get("sizeBytes") or 0) for i in items if i.get("queueState") == "pending_idle"),
            "keptCount": len(kept_items),
            "keptSizeBytes": sum(int(i.get("sizeBytes") or 0) for i in kept_items),
            "dueCount": len(due_items),
            "dueSizeBytes": sum(int(i.get("sizeBytes") or 0) for i in due_items),
        },
        "deleted": delete_stats,
        "range": {
            "start": start_dt.date().isoformat(),
            "end": end_dt.date().isoformat(),
            "granularity": granularity,
        },
        "timeline": timeline,
    }
    return out, None


def build_stats_summary(stats: dict, deleted_recent_days: int = 30) -> dict:
    current = stats.get("current", {}) or {}
    deleted = stats.get("deleted", {}) or {}
    pending_count = int(current.get("pendingCount") or 0)
    pending_size = int(current.get("pendingSizeBytes") or 0)
    kept_count = int(current.get("keptCount") or 0)
    kept_size = int(current.get("keptSizeBytes") or 0)
    return {
        "pending": {
            "count": pending_count,
            "sizeBytes": pending_size,
        },
        "pendingWatched": {
            "count": int(current.get("pendingWatchedCount") or 0),
            "sizeBytes": int(current.get("pendingWatchedSizeBytes") or 0),
        },
        "pendingIdle": {
            "count": int(current.get("pendingIdleCount") or 0),
            "sizeBytes": int(current.get("pendingIdleSizeBytes") or 0),
        },
        "due": {
            "count": int(current.get("dueCount") or 0),
            "sizeBytes": int(current.get("dueSizeBytes") or 0),
        },
        "kept": {
            "count": kept_count,
            "sizeBytes": kept_size,
        },
        "tracked": {
            "count": pending_count + kept_count,
            "sizeBytes": pending_size + kept_size,
        },
        "deletedRecent": {
            "count": int(deleted.get("recentCount") or 0),
            "sizeBytes": int(deleted.get("recentSizeBytes") or 0),
            "days": max(int(deleted_recent_days or 0), 1),
        },
        "deletedTotal": {
            "count": int(deleted.get("totalCount") or 0),
            "sizeBytes": int(deleted.get("totalSizeBytes") or 0),
        },
    }


def _merge_settings(base_ui: dict, incoming: dict) -> dict:
    merged = json.loads(json.dumps(base_ui))
    for key in ("usernames", "username", "monitor_all_users", "monitor_all_libraries", "general"):
        if key in incoming:
            merged[key] = incoming[key]
    for block in ("jellyfin", "radarr", "sonarr", "download_clients"):
        if not isinstance(incoming.get(block), dict):
            continue
        if block == "download_clients":
            for sub in ("qbittorrent", "deluge"):
                if isinstance(incoming[block].get(sub), dict):
                    merged.setdefault(block, {}).setdefault(sub, {}).update(incoming[block][sub])
        else:
            merged.setdefault(block, {}).update(incoming[block])
    return merged


def run_connection_test(service: str, ui_settings: dict) -> tuple[bool, str]:
    svc = service.strip().lower()
    if svc == "jellyfin":
        jelly = ui_settings.get("jellyfin", {}) or {}
        return test_jellyfin_connection(str(jelly.get("base_url") or "").strip(), str(jelly.get("api_key") or "").strip())
    if svc == "radarr":
        radarr = ui_settings.get("radarr", {}) or {}
        return test_radarr_connection(str(radarr.get("base_url") or "").strip(), str(radarr.get("api_key") or "").strip())
    if svc == "sonarr":
        sonarr = ui_settings.get("sonarr", {}) or {}
        return test_sonarr_connection(str(sonarr.get("base_url") or "").strip(), str(sonarr.get("api_key") or "").strip())
    if svc == "qbittorrent":
        qbt = ((ui_settings.get("download_clients") or {}).get("qbittorrent") or {})
        return test_qbittorrent_connection(
            str(qbt.get("base_url") or "").strip(),
            str(qbt.get("username") or "").strip(),
            str(qbt.get("password") or ""),
        )
    if svc == "deluge":
        deluge = ((ui_settings.get("download_clients") or {}).get("deluge") or {})
        return test_deluge_connection(
            str(deluge.get("base_url") or "").strip(),
            str(deluge.get("password") or ""),
        )
    return False, "unsupported service"


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, code: int, payload: dict, extra_headers: dict[str, str] | None = None):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str):
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _get_signed_user(self) -> dict | None:
        sid = parse_cookie_value(self.headers.get("Cookie"), "jc_session")
        return get_session(sid)

    def _require_auth(self):
        user = self._get_signed_user()
        if not user:
            self._send_json(401, {"ok": False, "error": "authentication required"})
            return None
        return user

    def _fallback_monitor_usernames(self) -> list[str]:
        user = self._get_signed_user() or {}
        name = str(user.get("name") or "").strip()
        return [name] if name else []

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            return self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        if path == "/app.js":
            return self._send_file(STATIC_DIR / "app.js", "application/javascript; charset=utf-8")
        if path == "/tailwind.css":
            return self._send_file(STATIC_DIR / "tailwind.css", "text/css; charset=utf-8")
        if path == "/styles.css":
            return self._send_file(STATIC_DIR / "styles.css", "text/css; charset=utf-8")
        if path == "/site.webmanifest":
            return self._send_file(STATIC_DIR / "site.webmanifest", "application/manifest+json; charset=utf-8")
        if path.startswith("/icons/"):
            rel = path.removeprefix("/icons/")
            icon_path = (STATIC_DIR / "icons" / rel).resolve()
            icons_root = (STATIC_DIR / "icons").resolve()
            if icons_root not in icon_path.parents and icon_path != icons_root:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            suffix = icon_path.suffix.lower()
            content_type = {
                ".svg": "image/svg+xml",
                ".png": "image/png",
                ".ico": "image/x-icon",
                ".webp": "image/webp",
            }.get(suffix, "application/octet-stream")
            return self._send_file(icon_path, content_type)

        if path == "/api/health":
            return self._send_json(200, {"ok": True})

        if path == "/api/auth/status":
            user = self._get_signed_user()
            return self._send_json(200, {"ok": True, "authenticated": bool(user), "user": user or None})

        if path.startswith("/api/"):
            if path != "/api/stats/summary" and self._require_auth() is None:
                return

        if path == "/api/settings":
            try:
                return self._send_json(200, {"ok": True, "settings": config_for_ui(read_config())})
            except Exception as exc:
                return self._send_json(500, {"ok": False, "error": str(exc)})

        if path == "/api/jellyfin-users":
            try:
                cfg = read_config()
                jelly = cfg.get("jellyfin", {}) or {}
                base = str(jelly.get("base_url") or "").strip()
                key = str(jelly.get("api_key") or "").strip()
                if not base or not key:
                    return self._send_json(200, {"ok": True, "users": []})
                users = get_jellyfin_users(base, key)
                names = sorted([str(u.get("Name") or "").strip() for u in users if str(u.get("Name") or "").strip()])
                return self._send_json(200, {"ok": True, "users": names})
            except Exception as exc:
                return self._send_json(500, {"ok": False, "error": str(exc)})

        if path == "/api/jellyfin-libraries":
            try:
                cfg = read_config()
                jelly = cfg.get("jellyfin", {}) or {}
                base = str(jelly.get("base_url") or "").strip()
                key = str(jelly.get("api_key") or "").strip()
                if not base or not key:
                    return self._send_json(200, {"ok": True, "libraries": []})
                users = get_jellyfin_users(base, key)
                if not users:
                    return self._send_json(200, {"ok": True, "libraries": []})
                usernames = get_config_usernames(cfg)
                if not usernames and not bool(cfg.get("monitor_all_users", False)):
                    usernames = self._fallback_monitor_usernames()
                by_name = {str(u.get("Name") or "").strip().lower(): u for u in users}
                target = users[0]
                if usernames:
                    hit = by_name.get(usernames[0].strip().lower())
                    if hit is not None:
                        target = hit
                libs = get_jellyfin_libraries(base, key, str(target.get("Id") or ""))
                return self._send_json(200, {"ok": True, "libraries": libs})
            except Exception as exc:
                return self._send_json(500, {"ok": False, "error": str(exc)})

        if path == "/api/data":
            qs = parse_qs(parsed.query)
            force = qs.get("force", ["0"])[0] == "1"
            payload, err = get_payload(force=force, fallback_usernames=self._fallback_monitor_usernames())
            if payload is None:
                return self._send_json(500, {"ok": False, "error": err or "unknown error"})
            status_filter = qs.get("status", [""])[0].strip()
            if status_filter:
                payload = {
                    **payload,
                    "items": [
                        i for i in payload["items"]
                        if i.get("queueState") == status_filter or i.get("status") == status_filter
                    ],
                }
            return self._send_json(200, {"ok": True, **payload})

        if path == "/api/stats":
            qs = parse_qs(parsed.query)
            force = qs.get("force", ["0"])[0] == "1"
            days = _as_int(qs.get("days", ["30"])[0], 30, 1)
            start = qs.get("start", [""])[0].strip() or None
            end = qs.get("end", [""])[0].strip() or None
            all_data = _as_bool(qs.get("all", ["0"])[0], False)
            stats, err = build_stats(
                force=force,
                days=days,
                start=start,
                end=end,
                all_data=all_data,
                fallback_usernames=self._fallback_monitor_usernames(),
            )
            if stats is None:
                return self._send_json(500, {"ok": False, "error": err or "unknown error"})
            return self._send_json(200, {"ok": True, **stats})

        if path == "/api/stats/summary":
            ok, auth_err = _is_machine_api_authorized(self.headers)
            if not ok:
                return self._send_json(401, {"ok": False, "error": auth_err or "unauthorized"})
            qs = parse_qs(parsed.query)
            force = qs.get("force", ["0"])[0] == "1"
            stats, err = build_stats(force=force)
            if stats is None:
                return self._send_json(500, {"ok": False, "error": err or "unknown error"})
            return self._send_json(
                200,
                {
                    "ok": True,
                    "generatedAt": utc_now().isoformat(),
                    "current": stats.get("current", {}),
                    "deleted": stats.get("deleted", {}),
                    "summary": build_stats_summary(stats),
                },
            )

        if path.startswith("/api/image/"):
            item_id = path.split("/api/image/")[-1]
            try:
                cfg = read_config()
                jelly = cfg.get("jellyfin", {})
                base = jelly.get("base_url")
                key = jelly.get("api_key")
                url = f"{base.rstrip('/')}/Items/{item_id}/Images/Primary"
                req = Request(url, headers={"X-Emby-Token": key})
                with urlopen(req, timeout=20) as resp:
                    blob = resp.read()
                    ctype = resp.headers.get("Content-Type", "image/jpeg")
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(blob)))
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                self.wfile.write(blob)
                return
            except Exception:
                self.send_error(HTTPStatus.NOT_FOUND)
                return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/auth/login":
            try:
                payload = self._read_json()
                username = str(payload.get("username") or "").strip()
                password = str(payload.get("password") or "")
                remember = _as_bool(payload.get("remember"), True)
                cfg = read_config()
                jelly = cfg.get("jellyfin", {}) or {}
                base = str(jelly.get("base_url") or "").strip()
                if not base:
                    return self._send_json(500, {"ok": False, "error": "Jellyfin base URL is not configured"})
                if not username or not password:
                    return self._send_json(400, {"ok": False, "error": "username and password are required"})
                auth = jellyfin_authenticate(base, username, password)
                user_obj = auth.get("User") or {}
                if not auth.get("AccessToken") or not user_obj:
                    return self._send_json(401, {"ok": False, "error": "invalid Jellyfin credentials"})
                role = "Administrator" if bool((user_obj.get("Policy") or {}).get("IsAdministrator")) else "User"
                signed = {"name": str(user_obj.get("Name") or username), "role": role}
                ttl = SESSION_TTL_SECONDS if remember else SESSION_BROWSER_TTL_SECONDS
                sid = create_session(signed, ttl)
                cookie = f"jc_session={sid}; Path=/; HttpOnly; SameSite=Lax"
                if remember:
                    cookie += f"; Max-Age={SESSION_TTL_SECONDS}"
                return self._send_json(200, {"ok": True, "user": signed}, extra_headers={"Set-Cookie": cookie})
            except HTTPError as exc:
                if exc.code in {401, 403}:
                    return self._send_json(401, {"ok": False, "error": "invalid Jellyfin credentials"})
                return self._send_json(502, {"ok": False, "error": f"Jellyfin authentication failed ({exc.code})"})
            except URLError as exc:
                return self._send_json(502, {"ok": False, "error": f"Could not reach Jellyfin: {exc.reason}"})
            except json.JSONDecodeError:
                return self._send_json(400, {"ok": False, "error": "invalid json"})
            except Exception as exc:
                return self._send_json(500, {"ok": False, "error": str(exc)})

        if parsed.path == "/api/auth/logout":
            sid = parse_cookie_value(self.headers.get("Cookie"), "jc_session")
            delete_session(sid)
            cookie = "jc_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
            return self._send_json(200, {"ok": True}, extra_headers={"Set-Cookie": cookie})

        if parsed.path.startswith("/api/"):
            if self._require_auth() is None:
                return

        if parsed.path == "/api/keep":
            try:
                payload = self._read_json()
                key = str(payload.get("key", "")).strip()
                keep = bool(payload.get("keep", False))
                if not key:
                    return self._send_json(400, {"ok": False, "error": "missing key"})
                set_keep_override(key, keep)
                get_payload(force=True)
                return self._send_json(200, {"ok": True, "key": key, "keep": keep})
            except json.JSONDecodeError:
                return self._send_json(400, {"ok": False, "error": "invalid json"})
            except Exception as exc:
                return self._send_json(500, {"ok": False, "error": str(exc)})

        if parsed.path == "/api/delete-now":
            try:
                payload = self._read_json()
                key = str(payload.get("key", "")).strip()
                if not key:
                    return self._send_json(400, {"ok": False, "error": "missing key"})
                result = delete_now(key)
                get_payload(force=True)
                return self._send_json(200, {"ok": True, "result": result})
            except json.JSONDecodeError:
                return self._send_json(400, {"ok": False, "error": "invalid json"})
            except Exception as exc:
                return self._send_json(500, {"ok": False, "error": str(exc)})

        if parsed.path == "/api/bulk-action":
            try:
                payload = self._read_json()
                mode = str(payload.get("mode", "")).strip().lower()
                keys = payload.get("keys") or []
                if not isinstance(keys, list):
                    return self._send_json(400, {"ok": False, "error": "keys must be an array"})
                result = bulk_action(keys, mode)
                get_payload(force=True)
                return self._send_json(200, {"ok": True, "result": result})
            except json.JSONDecodeError:
                return self._send_json(400, {"ok": False, "error": "invalid json"})
            except Exception as exc:
                return self._send_json(500, {"ok": False, "error": str(exc)})

        if parsed.path == "/api/settings":
            try:
                payload = self._read_json()
                write_config(payload)
                get_payload(force=True)
                return self._send_json(200, {"ok": True})
            except json.JSONDecodeError:
                return self._send_json(400, {"ok": False, "error": "invalid json"})
            except Exception as exc:
                return self._send_json(500, {"ok": False, "error": str(exc)})

        if parsed.path == "/api/test-connection":
            try:
                payload = self._read_json()
                service = str(payload.get("service") or "").strip().lower()
                base_ui = config_for_ui(read_config())
                ui_settings = _merge_settings(base_ui, payload.get("settings") or {})
                ok, detail = run_connection_test(service, ui_settings)
                return self._send_json(200, {"ok": True, "service": service, "connected": ok, "detail": detail})
            except json.JSONDecodeError:
                return self._send_json(400, {"ok": False, "error": "invalid json"})
            except Exception as exc:
                return self._send_json(500, {"ok": False, "error": str(exc)})

        self.send_error(HTTPStatus.NOT_FOUND)

    def log_message(self, fmt, *args):
        return


def main():
    init_db()
    server = ThreadingHTTPServer((APP_HOST, APP_PORT), Handler)
    print(f"jellycleanerr-gui listening on http://{APP_HOST}:{APP_PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
