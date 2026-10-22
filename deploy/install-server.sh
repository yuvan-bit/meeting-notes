#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/meeting-notes
DATA_DIR=/var/lib/meeting-notes
ENV_FILE=/etc/meeting-notes.env

if [[ ${EUID} -ne 0 ]]; then
  echo "请使用 root 运行本脚本" >&2
  exit 1
fi

if [[ ! -f "${APP_DIR}/server/__main__.py" ]]; then
  echo "未找到 ${APP_DIR}/server/__main__.py，请先解压部署包" >&2
  exit 1
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("需要 Python 3.10 或更高版本")
print("python", sys.version.split()[0])
PY

AVAILABLE_KB=$(awk '/MemAvailable/ {print $2}' /proc/meminfo)
if [[ -z "${AVAILABLE_KB}" || ${AVAILABLE_KB} -lt 307200 ]]; then
  echo "可用内存不足 300 MiB（当前 ${AVAILABLE_KB:-未知} KiB），已中止部署" >&2
  exit 1
fi

if ss -ltnH | awk '{print $4}' | grep -qE '(^|:)8000$'; then
  if ! systemctl is-active --quiet meeting-notes.service 2>/dev/null; then
    echo "端口 8000 已被其他进程占用，已中止部署" >&2
    exit 1
  fi
fi

if ! getent group meeting >/dev/null; then
  groupadd --system meeting
fi
if ! id meeting >/dev/null 2>&1; then
  useradd --system --gid meeting --home-dir "${DATA_DIR}" --no-create-home \
    --shell /usr/sbin/nologin meeting
fi
install -d -o meeting -g meeting -m 700 "${DATA_DIR}"

if ! dpkg -s python3-venv >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq python3-venv
fi

if [[ ! -x "${APP_DIR}/.venv/bin/python" ]]; then
  python3 -m venv "${APP_DIR}/.venv"
fi
"${APP_DIR}/.venv/bin/pip" install --disable-pip-version-check -q --upgrade pip
"${APP_DIR}/.venv/bin/pip" install --disable-pip-version-check -q \
  -r "${APP_DIR}/deploy/server-requirements.lock.txt"

chown -R root:root "${APP_DIR}"
chmod -R u+rwX,go+rX "${APP_DIR}"

if [[ ! -f "${ENV_FILE}" ]]; then
  cat > "${ENV_FILE}" <<'ENV'
MEETING_DATA_DIR=/var/lib/meeting-notes
MEETING_HOST=127.0.0.1
MEETING_PORT=8000
MEETING_AUDIO_MAX_MB=5120
MEETING_AUDIO_RETENTION_DAYS=30
ENV
  chown root:meeting "${ENV_FILE}"
  chmod 640 "${ENV_FILE}"
fi

install -m 644 "${APP_DIR}/deploy/systemd/meeting-notes.service" /etc/systemd/system/
install -m 644 "${APP_DIR}/deploy/systemd/meeting-notes-cleanup.service" /etc/systemd/system/
install -m 644 "${APP_DIR}/deploy/systemd/meeting-notes-cleanup.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable meeting-notes.service >/dev/null
systemctl restart meeting-notes.service
systemctl enable --now meeting-notes-cleanup.timer >/dev/null

"${APP_DIR}/.venv/bin/python" - <<'PY'
import json
import time
import urllib.request

last_error = None
for _ in range(30):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2) as response:
            print(json.dumps(json.load(response), ensure_ascii=False))
            break
    except Exception as exc:  # noqa: BLE001 - 启动期重试
        last_error = exc
        time.sleep(1)
else:
    raise SystemExit(f"健康检查失败：{last_error}")
PY

systemctl --no-pager --full status meeting-notes.service | head -n 12
systemctl show meeting-notes.service -p ActiveState -p SubState -p MemoryCurrent -p NRestarts
systemctl list-timers meeting-notes-cleanup.timer --no-pager
