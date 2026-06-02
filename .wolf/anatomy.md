# anatomy.md

> Auto-maintained by OpenWolf. Last scanned: 2026-06-02T03:32:09.783Z
> Files: 60 tracked | Anatomy hits: 0 | Misses: 0

## ./

- `.gitignore` — Git 忽略规则；排除 Videos/cache/logs/Python cache/Playwright browsers/前端 node_modules 和 dist 等本地产物。 (~180 tok)
- `CLAUDE.md` — OpenWolf (~1508 tok)
- `extract_slides.py` — 从文件管线 keyframe manifest 或流管线 payload 收集 slide 帧，去重后输出 `Slides/<base>/slides.pdf` 和可选 PPTX；流模式使用 `--stream-base`。 (~12000 tok)
- `run_dual_model.py` — Run dual-model verification (Gemini + Qwen) on a single video. (~4204 tok)
- `run_replay_qwen.bat` (~631 tok)
- `run_single_file.py` — Run zhihuTTS file pipeline on a single video for A/B testing. (~280 tok)
- `run_zhihu_live.bat` (~1231 tok)
- `START_LIVE.bat` (~472 tok)
- `stream_extractors.py` — class: is_ytdlp_stream_ended_error, infer_media_type, analyze_url_route, extract_with_ytdlp + 1 more (~6476 tok)
- `utils.py` — Shared utilities + Qwen QC: call_gemini/call_qwen、extract_qwen_critical_facts、extract_qwen_narrative_blocks、ensure_qwen_critical/narrative_appendix、check_qwen_notebooklm_quality、check_qwen_fact/narrative_retention。 (~8796 tok)
- `zhihuTTS_stream.py` — StreamSliceError: build_stream_gemini_parts, parse_time, fmt_time, safe_name + 1 more (~14162 tok)
- `zhihuTTS_video.py` — 关键帧提取 + SenseVoice/Whisper 转写（_sensevoice_model_cache 单例，避免每 chunk 重复加载 AutoModel）。 (~8432 tok)

## .claude/


## .claude/rules/

- `review.md` — AI 审查工作流 (~348 tok)

## .wolf/

- `anatomy.md` — File navigation index for the current workspace. (~164 tok)
- `cerebrum.md` — OpenWolf persistent learnings, user preferences, do-not-repeat notes, and decisions. (~5200 tok)
- `OPENWOLF.md` — OpenWolf session protocol and memory rules. (~1638 tok)

## C:/Users/Admin/.claude/projects/D--zhihu-zhihu/memory/


## C:/Users/Admin/AppData/Local/Temp/whisper-src/whisper_cpp_python-0.2.0/


## C:/Users/Admin/AppData/Roaming/Python/Python314/site-packages/whisper_cpp_python/


## Markdowns/


## docs/

- `docs/AB_TEST_RUNBOOK_20260526.md` — Gemini 3.5 Flash vs Qwen3.6-Flash A/B 测试操作手册；包含依赖安装、回放同 base 双合成、今晚直播双进程命令、单采集双合成替代方案和对比指标。 (~2600 tok)
- `docs/API_PROVIDER_OPTIMIZATION_PLAN_20260526.md` — MAC 端 API provider 优化方案：保留 Gemini、显式引入 Qwen provider、先试点 build_stream_markdown，再做预处理/合成解耦、短视频打包和 Batch API。 (~5200 tok)
- `docs/BUG_REPORT_20260526.md` — WIN 回放 A/B 测试 bug report；记录 `--cleanup-slices` 误删 global-transcript/payload/report 的 critical fix，以及 Qwen openai 依赖、Gemini 503 重试和首轮 A/B 摘要。 (~1200 tok)
- `docs/FRONTEND_PRODUCT_DESIGN_20260602.md` — zhihu 前端产品化功能设计；定义 MP4/回放/直播输入、Runs/Run Detail、产物/QC/关键帧/逐字稿/Markdown 可视化、P0-P2 范围和 API 边界。 (~5200 tok)
- `docs/handoff-20260601-live.md` — WIN 2026-06-01 知乎直播输出交接和 bug report；记录启动方式、greenlet 结束崩溃、Qwen max-frames/window 问题、产物清单和 Mac 端行动项。 (~1800 tok)
- `docs/LIVE_AB_TEST_PREP_20260526.md` — 今晚实时直播 Gemini/Qwen 双进程 A/B 执行清单；包含开播前预检、正式启动命令、直播中监控、产物路径、对比记录项、停止条件和单采集双合成降级方案。 (~2600 tok)
- `docs/LIVE_FINAL_QUALITY_ROADMAP.md` — 直播流质量提升路线图，P0→P1→P2，18个带验证标准的 checkbox 任务，进度表。 (~2800 tok)
- `docs/LIVE_STREAM_OPTIMIZATION_BACKLOG_20260521.md` — 旧版问题 backlog，已被 ROADMAP 取代。 (~100 tok)
- `docs/qwen_api_migration_analysis.md` — WIN 端关于从 Gemini 迁移/增补到 Qwen API 的可行性分析，围绕配额、OpenAI-compatible 接入、风险和迁移策略供 MAC review。 (~4200 tok)
- `docs/QWEN_LONG_VIDEO_OPTIMIZATION_PLAN_20260526.md` — Qwen 长视频 NotebookLM 文档优化计划；记录保真抽取优先、动态滑动窗口、frame 覆盖、QC 门禁和混合 Glossary/body 策略。 (~2600 tok)
- `docs/SHORT_VIDEO_QWEN_WORKFLOW_DESIGN_20260527.md` — Qwen 短视频批量抽取工作流设计；定义 preprocess-only、synthesize-only、packing、VIDEO_ID 拆分、短视频 QC、CLI 和 P0-P3 实施阶段。 (~7600 tok)
- `docs/TOUTIAO_FAVORITES_RUNBOOK.md` — 今日头条收藏夹同步运行手册；说明登录态保存、收藏页探测、manifest 更新、下载到 Videos/short/toutiao 以及接短视频 pipeline 的命令。 (~2500 tok)
- `FRONTEND_DASHBOARD_DESIGN.md` — 直播转写控制台 — 前端设计需求 (~1076 tok)
- `LIVE_FINAL_QUALITY_ROADMAP.md` — Live Final Quality Roadmap (~3188 tok)
- `LIVE_STREAM_SOP.md` — 知乎直播转写标准操作流程 (SOP) (~1727 tok)
- `WIN_LIVE_QWEN_WINDOW_FIX_VALIDATION_20260530.md` — WIN 验证交接：Qwen 滑动窗口 overlap 修复验证 (~439 tok)

## frontend/

- `frontend/index.html` — Vite React 前端 HTML 入口，挂载 `src/main.tsx`。 (~80 tok)
- `frontend/package.json` — zhihu Pipeline Workbench 前端依赖和脚本；React/Vite/TypeScript/lucide，支持 dev/build/preview。 (~180 tok)
- `frontend/tsconfig.json` — React TypeScript 编译配置。 (~180 tok)
- `frontend/tsconfig.node.json` — Vite config TypeScript 编译引用配置。 (~80 tok)
- `frontend/vite.config.ts` — Vite 配置；本地 dev server 端口 5173，并将 `/api` 代理到 `127.0.0.1:8765`。 (~120 tok)

## frontend/src/

- `frontend/src/api.ts` — 前端 API 客户端；调用 `/api/runs`、`/api/runs/{id}`、`POST /api/run-plans`、`POST /api/runs`，runs API 不可用时回退到 2026-06-01 live sample。 (~1600 tok)
- `frontend/src/App.tsx` — Pipeline Workbench 主 UI；包含可切换的 Create Source dry-run 表单、Dry Run Plan 保存、Runs 列表、Run Detail tabs、Plan/Logs/Overview/Chunks/QC/Keyframes/Transcript/Markdown 视图。 (~6200 tok)
- `frontend/src/main.tsx` — React root 挂载入口。 (~80 tok)
- `frontend/src/styles.css` — Workbench 全局样式，定义双栏布局、source 表单、dry-run plan、运行卡片、日志列表、指标条、流程线、表格、QC、关键帧和文本预览。 (~5400 tok)
- `frontend/src/types.ts` — Run、Artifact、PipelineStep、Chunk、Frame、QC、RunPlan/RunPlanRequest、RunLogEntry 等前端数据类型。 (~1300 tok)

## githooks/


## runs/

- `runs/stream-replay-ab-20260526-20260526-145918.gemini35.final-qc.json` — Gemini A/B final QC；source_status=partial、frame_count=0、body_coverage_status=ok、body_tail_gap_s=58。 (~500 tok)
- `runs/stream-replay-ab-20260526-20260526-145918.qwen.final-qc.json` — Qwen A/B final QC；source_status=partial、frame_count=0、body_coverage_status=ok、body_tail_gap_s=60，记录 Qwen usage 40,325 tokens。 (~600 tok)

## scripts/

- `build_stream_markdown.py` — Post-stream LLM synthesis: assemble all live chunks → NotebookLM document. (~24379 tok)
- `convert_payload_to_chunks.py` — Convert single payload.json to per-chunk stream format for build_stream_markdown.py. (~1548 tok)
- `live_sectioned_synthesis.py` — P1 Sectioned Synthesis: three-pass pipeline for live-stream final documents. (~30063 tok)
- `merge_stream_chunks.py` — parse_chunk_start, parse_timestamp, load_chunk_lines, load_chunk_slides (~2020 tok)
- `scripts/build_stream_markdown.py` — P0 live final synthesis入口；支持 Gemini/Qwen one-shot、Qwen `--synthesis-pass sliding-window` 窗口 notes+最终组装、final-qc/body/Qwen NotebookLM QC、预算 dry-run，并确定性追加完整逐字稿/视觉证据索引。 (~12000 tok)
- `scripts/check_auth.py` — 鉴权检查工具。 (~80 tok)
- `scripts/live_sectioned_synthesis.py` — P1-P2 分层合成主模块。新增 `run_full_pipeline()` 公共入口（Fix1）。Fix2: evidence hash 含 cleaned_transcript+frame type/ts+stale传播。Fix3: slide边界 frame key 归一化。Fix4: 术语词边界。 (~23000 tok)
- `scripts/merge_stream_chunks.py` — 合并 stream chunk 文件。 (~300 tok)
- `scripts/short_video_pipeline.py` — Qwen 短视频批量入口；支持 preprocess payload、synthesize dry-run pack plan、call-pack Qwen/mock 输出、split-pack 按 VIDEO_ID 拆 Markdown/QC、status 和 mock-payloads。 (~11000 tok)
- `scripts/terminology.json` — 项目术语表，9 条规则（Claude Code/RAG/MCP 等），供 normalize_transcript 使用。 (~60 tok)
- `scripts/toutiao_common.py` — 今日头条收藏同步公共工具；定义 cache/auth/manifest/video 路径、URL/ID 规范化、manifest merge、Playwright context 和 storage_state 到 yt-dlp cookie 转换。 (~3300 tok)
- `scripts/toutiao_download_favorites.py` — 从 cache/toutiao/manifest.json 下载今日头条收藏视频；优先 yt-dlp，失败后 Playwright 捕获媒体 URL + ffmpeg，落盘 Videos/short/toutiao。 (~3000 tok)
- `scripts/toutiao_login.py` — 打开 Playwright 有头浏览器登录今日头条，并保存登录态到 cache/toutiao/auth_state.json。 (~700 tok)
- `scripts/toutiao_probe_favorites.py` — 使用 Playwright 登录态打开今日头条收藏页、滚动探测视频链接/网络候选项，可写 probe JSON、screenshot 并更新 manifest。 (~2700 tok)

## web_api/

- `web_api/README.md` — 本地 Web API 说明；记录 `GET /api/runs`、`GET /api/runs/{id}`、`POST /api/run-plans`、`POST /api/runs` 和启动命令。 (~180 tok)
- `web_api/server.py` — 纯标准库本地 API；扫描 `runs/*.final-qc.json`，关联 manifest、transcript、Markdown、chunks、payload frames，输出前端 Run 数据；新增 dry-run plan 生成和本地 created run registry，不启动长任务。 (~6800 tok)
