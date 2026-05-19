#!/usr/bin/env bash
# ============================================================
# run_zhihu_live.sh  知乎直播流一键转写 (Mac/Linux)
#
# 用法:
#   ./run_zhihu_live.sh <直播间URL> [输出名]
#
# 示例:
#   ./run_zhihu_live.sh "https://www.zhihu.com/xen/training/live/room/xxx" gaowei-20260519
#   ./run_zhihu_live.sh "https://www.zhihu.com/xen/training/live/room/xxx"
#     （不填名称时用 live-YYYYMMDD-HHMMSS 自动命名）
#
# 输出（位于 runs/ 目录）:
#   stream-<NAME>-<时间>.combined-transcript.txt   完整逐字转写
#   stream-<NAME>-<时间>.manifest.md               逐块统计
#   stream-<NAME>-<时间>.notes.md                  Gemini 结构化笔记（需要 GEMINI_API_KEY）
#
# 依赖（首次使用前确认）:
#   1. ./run_zhihu_live.sh --login   扫码登录，生成 zhihu_auth_state.json
#   2. export GEMINI_API_KEY=...     （可选，不设则跳过笔记生成）
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="${HOME}/.venv-sensevoice/bin/python"
AUTH_STATE="${SCRIPT_DIR}/zhihu_auth_state.json"
STREAM_WORK_DIR="${SCRIPT_DIR}/Videos/.stream"

# merge_vad=true 适合 60s 分片（短片段内 VAD 合并让文本更连贯）
export SENSEVOICE_MERGE_VAD=true

PAGE_URL="${1:-}"
NAME="${2:-}"

# ---- 登录快捷方式 ----
if [[ "${PAGE_URL}" == "--login" ]]; then
    echo "启动登录流程..."
    "${VENV_PYTHON}" "${SCRIPT_DIR}/login_save_auth.py"
    exit $?
fi

# ---- 自动生成名称（未提供时）----
if [[ -z "${NAME}" ]]; then
    NAME="live-$(date +%Y%m%d-%H%M%S)"
fi

# ---- URL 检查（无参数时交互式输入）----
if [[ -z "${PAGE_URL}" ]]; then
    echo ""
    echo "请粘贴知乎直播间 URL，然后按回车："
    echo "（示例: https://www.zhihu.com/xen/training/live/room/...）"
    echo ""
    read -rp "URL: " PAGE_URL
    PAGE_URL="${PAGE_URL// /}"
fi
if [[ -z "${PAGE_URL}" ]]; then
    echo ""
    echo "[错误] 未输入 URL，退出。"
    exit 1
fi

# ---- Python 检查 ----
if [[ -x "${VENV_PYTHON}" ]]; then
    PYTHON="${VENV_PYTHON}"
else
    PYTHON="$(command -v python3 || command -v python)"
    echo "[提示] 未找到 venv python，使用系统 python（${PYTHON}）"
fi

# ---- 登录状态检查 ----
if [[ ! -f "${AUTH_STATE}" ]]; then
    echo ""
    echo "[错误] 未找到登录状态文件:"
    echo "  ${AUTH_STATE}"
    echo ""
    echo "请先运行一次登录:"
    echo "  ./run_zhihu_live.sh --login"
    echo ""
    exit 1
fi

# ---- Cookie 有效性检查 ----
"${PYTHON}" "${SCRIPT_DIR}/scripts/check_auth.py" "${AUTH_STATE}"
if [[ $? -ne 0 ]]; then
    echo ""
    echo "[错误] 登录 Cookie 已失效，请重新登录:"
    echo "  ./run_zhihu_live.sh --login"
    echo ""
    exit 1
fi

# ---- 提示信息 ----
echo ""
echo "===================================================="
echo " 知乎直播转写启动"
echo " 名称  : ${NAME}"
echo " URL   : ${PAGE_URL}"
echo " Auth  : ${AUTH_STATE}"
echo " 临时   : ${STREAM_WORK_DIR}"
if [[ -z "${GEMINI_API_KEY:-}" ]]; then
    echo " Gemini: 未设置 GEMINI_API_KEY，将跳过笔记生成"
else
    echo " Gemini: 已配置，直播结束后自动生成笔记"
fi
echo "===================================================="
echo ""

# ---- 运行 ----
"${PYTHON}" "${SCRIPT_DIR}/zhihuTTS_stream.py" \
  --playwright-keepalive \
  --page-url "${PAGE_URL}" \
  --playwright-storage-state "${AUTH_STATE}" \
  --playwright-save-storage-state "${AUTH_STATE}" \
  --duration 0 \
  --chunk-duration 60 \
  --stream-work-dir "${STREAM_WORK_DIR}" \
  --cleanup-slices \
  --name "${NAME}" \
  --gemini

EXIT_CODE=$?
echo ""
if [[ ${EXIT_CODE} -ne 0 ]]; then
    echo "[!] 脚本异常退出，退出码: ${EXIT_CODE}"
    exit ${EXIT_CODE}
fi

# ---- 分片合并 ----
echo "转写完成，正在合并分片为结构化 Markdown..."
echo ""
"${PYTHON}" "${SCRIPT_DIR}/scripts/merge_stream_chunks.py" \
  --base "${NAME}" \
  --runs-dir "${SCRIPT_DIR}/runs"

MERGE_EXIT=$?
echo ""
if [[ ${MERGE_EXIT} -ne 0 ]]; then
    echo "[提示] 分片合并失败或无幻灯片事件，手动运行:"
    echo "  python scripts/merge_stream_chunks.py --base ${NAME}"
else
    echo "结构化 Markdown 已生成: runs/stream-${NAME}-merged.md"
fi

echo ""
echo "全部输出文件在 runs/ 目录"
