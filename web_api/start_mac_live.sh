#!/bin/bash
# start_mac_live.sh — Mac 端本地真实任务模式
#
# 支持的任务类型：
#   ✅ MP4    — 拖入 Videos/ 目录下的文件，直接执行 run_single_file.py
#   ✅ Replay — 粘贴回放 URL，执行 zhihuTTS_stream.py --url（需要 zhihu_auth_state.json）
#   ❌ Live   — 直播流在 Mac 不可用；live pipeline 调用 run_zhihu_live.bat（WIN 专用）
#
# 与 start_mac_viewer.sh 的区别：
#   - 以 --launch-mode live 启动 API（而非 simulate）
#   - 激活 .venv-mac311，使用 faster-whisper 作为转写后端
#   - 不传 --readonly，允许写入和启动任务
#
# 用法：
#   ./web_api/start_mac_live.sh

set -e
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

VENV="$PROJECT_DIR/.venv-mac311"
if [ -f "$VENV/bin/activate" ]; then
    source "$VENV/bin/activate"
    echo "=== 已激活 $VENV ==="
else
    echo "[WARN] .venv-mac311 未找到，使用系统 Python"
fi

export TRANSCRIBE_BACKEND=faster-whisper
export PLAYWRIGHT_BROWSERS_PATH="$PROJECT_DIR/.playwright-browsers"

echo "=== MAC Live Mode: 启动本地 API（--launch-mode live）+ 前端 ==="
echo "    项目根目录 : $PROJECT_DIR"
echo "    API       : http://127.0.0.1:8765"
echo "    前端      : http://127.0.0.1:5173"
echo ""

python3 web_api/server.py --launch-mode live &
API_PID=$!
echo "API server 已启动 (PID $API_PID)"
sleep 1

npm run dev --prefix frontend

kill "$API_PID" 2>/dev/null || true
