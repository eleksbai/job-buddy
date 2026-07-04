#!/usr/bin/env bash
set -euo pipefail

DESKTOP_PID=$(pgrep -u "$USER" -x 'xfce4-session|Xorg' | tail -1)

if [[ -z "$DESKTOP_PID" ]]; then
  echo "错误: 未找到桌面会话进程 (xfce4-session / Xorg)" >&2
  exit 1
fi

while IFS= read -r -d '' line; do
  case "$line" in
    DISPLAY=*|XAUTHORITY=*|DBUS_SESSION_BUS_ADDRESS=*)
      export "$line"
      echo "export $(echo "$line" | cut -d= -f1)=..."
      ;;
  esac
done < "/proc/$DESKTOP_PID/environ"

: "${XAUTHORITY:=$HOME/.Xauthority}"
export XAUTHORITY

if [[ -z "${DISPLAY:-}" ]]; then
  echo "错误: 桌面会话中未找到 DISPLAY" >&2
  exit 1
fi

cd "$(dirname "$0")/.."
echo "DISPLAY=$DISPLAY  启动 job-buddy..."
exec uv run uvicorn job_buddy.main:app --host 0.0.0.0 --port 8000
