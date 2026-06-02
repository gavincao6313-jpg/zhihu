#!/bin/bash
# start_mac_viewer.sh — MAC 端只读查看器
#
# 用法 A — 连接 WIN 实时数据（推荐，同局域网）:
#   ./web_api/start_mac_viewer.sh <WIN_IP>
#   例: ./web_api/start_mac_viewer.sh 192.168.1.5
#
# 用法 B — 读取 git pull 到本地的 runs/ 数据:
#   ./web_api/start_mac_viewer.sh

set -e
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WIN_IP="${1:-}"
cd "$PROJECT_DIR"

if [ -n "$WIN_IP" ]; then
    echo "=== MAC Viewer: connecting to WIN at http://$WIN_IP:8765 ==="
    VITE_API_URL="http://$WIN_IP:8765" npm run dev --prefix frontend
else
    echo "=== MAC Viewer: local read-only mode ==="
    python3 web_api/server.py --readonly &
    API_PID=$!
    echo "Local read-only API started (PID $API_PID) on http://127.0.0.1:8765"
    sleep 1
    npm run dev --prefix frontend
    kill "$API_PID" 2>/dev/null || true
fi
