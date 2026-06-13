# anatomy.md

> Auto-maintained by OpenWolf. Last scanned: 2026-06-12T05:50:05.008Z
> Files: 42 tracked | Anatomy hits: 0 | Misses: 0

## ../../.claude/

- `settings.json` (~1243 tok)

## ../../.claude/plans/

- `expressive-noodling-dongarra.md` — 浏览器插件：网页朗读 (AI TTS) (~731 tok)

## ../../.claude/projects/-Users-caojiapeng-projects-zhihu/memory/


## ../browser-reader/

- `manifest.json` (~241 tok)

## ../browser-reader/background/

- `service-worker.js` — Service Worker：转发 popup ↔ content 消息 (~178 tok)

## ../browser-reader/content/

- `content.js` — 网页朗读 content script (~1983 tok)

## ../browser-reader/options/

- `options.html` — AI 网页朗读 - 设置 (~905 tok)
- `options.js` — apiKeyEl: showToast (~421 tok)

## ../browser-reader/popup/

- `popup.html` — AI 网页朗读 (~1013 tok)
- `popup.js` — Popup 控制逻辑 (~1164 tok)

## ./

- `capture_catalog.py` — 通过知乎 API 获取完整课程目录 (~864 tok)
- `debug_stream.py` — 诊断脚本：测试单个知乎视频页面的流拦截行为 (~1077 tok)
- `download_course_materials.py` — 下载知乎训练营课程"小结资料"PDF (~1834 tok)
- `extract_bilibili_cookies.py` — 用 Playwright 打开 Bilibili，扫码登录，保存 cookie 给 yt-dlp 用. (~931 tok)
- `extract_chrome_cookies.py` — Extract & decrypt Bilibili cookies from Chrome for yt-dlp. (~1480 tok)
- `probe_material_api.py` — 探查知乎小结资料 API (~668 tok)
- `probe_material.py` — 找到file_id来源 - 拦截所有XHR响应 (~930 tok)
- `retry_missing.py` — 补下缺失的视频 (~952 tok)
- `zhihu_download_v2.py` — safe_name, main, on_request (~1858 tok)

## .claude/


## .claude/rules/


## .githooks/

- `pre-commit` — 预提交检查：凭据拦截 + 仓库卫生 (~1204 tok)
- `pre-push` — 预推送检查：扫描待推送提交中的凭据/密钥 (~486 tok)

## .wolf/


## C:/Users/Admin/.claude/plans/

- `cosmic-weaving-sphinx.md` — 批量处理 `E:\AI产品经理课` 68个MP4视频 (~597 tok)

## C:/Users/Admin/.claude/projects/D--zhihu-zhihu/memory/


## C:/Users/Admin/.claude/projects/D--zhihu/memory/

- `ai_pm_course_batch_processing.md` — AI产品经理课 批量处理 (~560 tok)
- `download_tasks.md` — 下载任务清单 (~118 tok)
- `live-stream-sop.md` — 关键教训（v1.1 更新 — 2026-06-02 Mac 推送） (~393 tok)
- `MEMORY.md` (~145 tok)
- `xiaoe_live_startup.md` — 技术细节 (~276 tok)

## C:/Users/Admin/AppData/Local/Temp/whisper-src/whisper_cpp_python-0.2.0/


## C:/Users/Admin/AppData/Roaming/Python/Python314/site-packages/whisper_cpp_python/


## Markdowns/


## docs/


## frontend/


## frontend/src/


## githooks/


## runs/


## scripts/

- `zhihu_course_replay_downloader.py` — extract_training_id, safe_name, cookies_to_header, load_progress (~3865 tok)

## web_api/


## zhihu_file/

- `_check_manifest.py` — Check manifest status. (~149 tok)
- `_fix_progress_keys.py` — One-shot: transform progress file keys from flat _ separator to / subdir structure. (~339 tok)
- `_parse_probe_json.py` — One-shot: parse Toutiao video items from probe body_excerpt JSON. (~872 tok)
- `_quick_save_xiaoe_auth.py` — Quick save xiaoe auth — auto-detects login and saves without waiting for Enter. (~665 tok)
- `_sync_toutiao_api_v2.py` — Sync Toutiao favorites via API - try different pagination strategies. (~904 tok)
- `_sync_toutiao_api.py` — Sync all Toutiao favorites via direct API calls with pagination. (~1339 tok)
- `.gitignore` — Git ignore rules (~220 tok)
- `batch_process_external.py` — Batch process MP4 videos from an external directory through the (~9420 tok)
- `gen_slides_external.py` — Generate PDF + PPTX slides from externally-processed MP4 videos. (~738 tok)
- `save_xiaoe_auth.py` — Save xiaoe auth state — auto-detects login and saves without waiting for Enter. (~698 tok)
- `START_XIAOE_LIVE.bat` (~1229 tok)
- `zhihu_file/batch_process_external.py` — 外部目录MP4批量处理编排脚本：视频发现→时长探测→Gemini/Qwen自动路由→配额管控→检查点续跑 (~6500 tok)

## zhihu_file/docs/

- `LIVE_STREAM_SOP.md` — 知乎直播转写标准操作流程 (SOP) (~2113 tok)

## zhihu_file/scripts/

- `toutiao_common.py` — from: now_iso, ensure_dirs, slugify, canonical_url + 10 more (~2228 tok)
- `toutiao_probe_favorites.py` — collect_anchor_candidates, collect_json_body_candidates, probe_favorites, on_request (~2681 tok)
