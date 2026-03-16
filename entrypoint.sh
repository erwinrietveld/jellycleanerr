#!/bin/bash
set -euo pipefail

# Interval for periodic Jellycleanerr cleanup runs.
INTERVAL="${INTERVAL:-1h}"
CONFIG_PATH="${JELLYCLEANERR_CONFIG:-${SANITARR_CONFIG:-/config/config.toml}}"
LOG_LEVEL="${LOG_LEVEL:-info}"
FORCE_DELETE="${FORCE_DELETE:-true}"
IDLE_AUTO_DELETE="${IDLE_AUTO_DELETE:-true}"

# Start GUI API/web server.
python3 /opt/jellycleanerr/gui/app.py &
GUI_PID=$!

cleanup() {
  kill "${GUI_PID}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

build_jellycleanerr_cmd() {
  if [ "$#" -gt 0 ]; then
    echo "jellycleanerr $*"
    return
  fi

  local cmd="jellycleanerr --config ${CONFIG_PATH} --log-level ${LOG_LEVEL}"
  if [ "$(is_dry_run_enabled)" = "0" ]; then
    case "${FORCE_DELETE}" in
      1|true|TRUE|yes|YES|on|ON)
        cmd="${cmd} --force-delete"
        ;;
    esac
  fi
  echo "${cmd}"
}

is_dry_run_enabled() {
  python3 - "${CONFIG_PATH}" <<'PY'
import sys, tomllib
cfg_path = sys.argv[1]
try:
    with open(cfg_path, "rb") as f:
        cfg = tomllib.load(f)
except Exception:
    print("1")
    raise SystemExit
general = cfg.get("general") or {}
raw = str(general.get("dry_run", True)).strip().lower()
print("0" if raw in {"0", "false", "no", "off"} else "1")
PY
}

SAN_CMD="$(build_jellycleanerr_cmd "$@")"
echo "jellycleanerr gui on http://0.0.0.0:${PORT:-8282}"
echo "jellycleanerr cleanup command: ${SAN_CMD}"
echo "jellycleanerr cleanup interval: ${INTERVAL}"

run_default_cleanup_multi_user() {
  mapfile -t USERS < <(python3 - "${CONFIG_PATH}" <<'PY'
import sys, tomllib
cfg_path = sys.argv[1]
with open(cfg_path, "rb") as f:
    cfg = tomllib.load(f)
raw = cfg.get("usernames")
users = []
if isinstance(raw, list):
    users = [str(x).strip() for x in raw if str(x).strip()]
if not users:
    u = str(cfg.get("username") or "").strip()
    if u:
        users = [u]
for u in users:
    print(u)
PY
  )

  if [ "${#USERS[@]}" -eq 0 ]; then
    echo "no monitored users in config; skipping cleanup run"
    return
  fi

  for USERNAME in "${USERS[@]}"; do
    TMP_CONFIG="$(mktemp /tmp/jellycleanerr-config.XXXXXX.toml)"
    python3 - "${CONFIG_PATH}" "${TMP_CONFIG}" "${USERNAME}" <<'PY'
import sys, tomllib

src, dst, username = sys.argv[1], sys.argv[2], sys.argv[3]
with open(src, "rb") as f:
    cfg = tomllib.load(f)

cfg["username"] = username
allowed = {
    "username": cfg.get("username", ""),
    "jellyfin": cfg.get("jellyfin", {}) or {},
    "radarr": cfg.get("radarr", {}) or {},
    "sonarr": cfg.get("sonarr", {}) or {},
    "download_clients": cfg.get("download_clients", {}) or {},
}

def q(v):
    return '"' + str(v or "").replace("\\", "\\\\").replace('"', '\\"') + '"'

lines = [f"username = {q(allowed['username'])}", ""]

jelly = allowed["jellyfin"]
lines.extend(["[jellyfin]", f"base_url = {q(jelly.get('base_url', ''))}", f"api_key = {q(jelly.get('api_key', ''))}", ""])

rad = allowed["radarr"]
tags_rad = ", ".join(q(x) for x in (rad.get("tags_to_keep") or []))
lines.extend([
    "[radarr]",
    f"base_url = {q(rad.get('base_url', ''))}",
    f"api_key = {q(rad.get('api_key', ''))}",
    f"tags_to_keep = [{tags_rad}]",
    f"retention_period = {q(rad.get('retention_period', '60d'))}",
    f"unmonitor_watched = {'true' if rad.get('unmonitor_watched') else 'false'}",
    "",
])

son = allowed["sonarr"]
tags_son = ", ".join(q(x) for x in (son.get("tags_to_keep") or []))
lines.extend([
    "[sonarr]",
    f"base_url = {q(son.get('base_url', ''))}",
    f"api_key = {q(son.get('api_key', ''))}",
    f"tags_to_keep = [{tags_son}]",
    f"retention_period = {q(son.get('retention_period', '60d'))}",
    f"unmonitor_watched = {'true' if son.get('unmonitor_watched') else 'false'}",
    "",
])

dls = allowed["download_clients"]
qbt = dls.get("qbittorrent") or {}
if qbt.get("base_url") or qbt.get("username") or qbt.get("password"):
    lines.extend([
        "[download_clients.qbittorrent]",
        f"base_url = {q(qbt.get('base_url', ''))}",
        f"username = {q(qbt.get('username', ''))}",
        f"password = {q(qbt.get('password', ''))}",
        "",
    ])

deluge = dls.get("deluge") or {}
if deluge.get("base_url") or deluge.get("password"):
    lines.extend([
        "[download_clients.deluge]",
        f"base_url = {q(deluge.get('base_url', ''))}",
        f"password = {q(deluge.get('password', ''))}",
        "",
    ])

with open(dst, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
PY

    RUN_CMD="jellycleanerr --config ${TMP_CONFIG} --log-level ${LOG_LEVEL}"
    if [ "$(is_dry_run_enabled)" = "0" ]; then
      case "${FORCE_DELETE}" in
        1|true|TRUE|yes|YES|on|ON)
          RUN_CMD="${RUN_CMD} --force-delete"
          ;;
      esac
    fi
    echo "cleanup run for jellyfin user: ${USERNAME}"
    # shellcheck disable=SC2086
    ${RUN_CMD} || true
    rm -f "${TMP_CONFIG}"
  done
}

while true; do
  if ! kill -0 "${GUI_PID}" 2>/dev/null; then
    echo "GUI process exited; stopping container"
    exit 1
  fi

  if [ "$#" -gt 0 ]; then
    # shellcheck disable=SC2086
    ${SAN_CMD} || true
  else
    run_default_cleanup_multi_user
  fi
  case "${IDLE_AUTO_DELETE}" in
    1|true|TRUE|yes|YES|on|ON)
      if [ "$(is_dry_run_enabled)" = "1" ]; then
        echo "idle auto-delete: skipped (manual mode enabled)"
      else
        python3 - <<'PY'
import sys
sys.path.insert(0, "/opt/jellycleanerr/gui")
import app
try:
    out = app.auto_delete_idle_media()
    print(f"idle auto-delete: {out.get('deleted', 0)}/{out.get('total', 0)} deleted")
except Exception as exc:
    print(f"idle auto-delete failed: {exc}")
PY
      fi
      ;;
  esac
  sleep "${INTERVAL}"
done
