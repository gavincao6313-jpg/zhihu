# anatomy.md

> Auto-maintained by OpenWolf. Last scanned: 2026-05-27T15:31:48.427Z
> Files: 41 tracked | Anatomy hits: 0 | Misses: 0

## ../../../../tmp/

- `test_narrative_inject.py` (~819 tok)

## ./

- `CLAUDE.md` — OpenWolf (~1508 tok)
- `extract_slides.py` — 从文件管线 keyframe manifest 或流管线 payload 收集 slide 帧，去重后输出 `Slides/<base>/slides.pdf` 和可选 PPTX；流模式使用 `--stream-base`。 (~12000 tok)
- `run_single_file.py` — Run zhihuTTS file pipeline on a single video for A/B testing. (~280 tok)
- `run_zhihu_live.bat` (~4241 tok)
- `stream_extractors.py` — URL/page extractor layer for stream/replay inputs; routes known hosts to yt-dlp or Playwright, captures media URLs/headers, and manages Playwright keepalive for Zhihu live. (~9000 tok)
- `utils.py` — Shared utilities for zhihu pipeline scripts. (~3854 tok)
- `zhihuTTS_stream.py` — Stream/replay/live chunk capture and transcription pipeline; resolves stream `base_stem`, writes chunk artifacts/manifests, supports continuous HLS per-run work dirs, optional Gemini notes, and `--base-marker` for wrappers. (~18000 tok)

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
- `docs/LIVE_AB_TEST_PREP_20260526.md` — 今晚实时直播 Gemini/Qwen 双进程 A/B 执行清单；包含开播前预检、正式启动命令、直播中监控、产物路径、对比记录项、停止条件和单采集双合成降级方案。 (~2600 tok)
- `docs/LIVE_FINAL_QUALITY_ROADMAP.md` — 直播流质量提升路线图，P0→P1→P2，18个带验证标准的 checkbox 任务，进度表。 (~2800 tok)
- `docs/LIVE_STREAM_OPTIMIZATION_BACKLOG_20260521.md` — 旧版问题 backlog，已被 ROADMAP 取代。 (~100 tok)
- `docs/qwen_api_migration_analysis.md` — WIN 端关于从 Gemini 迁移/增补到 Qwen API 的可行性分析，围绕配额、OpenAI-compatible 接入、风险和迁移策略供 MAC review。 (~4200 tok)
- `docs/QWEN_LONG_VIDEO_OPTIMIZATION_PLAN_20260526.md` — Qwen 长视频 NotebookLM 文档优化计划；记录保真抽取优先、动态滑动窗口、frame 覆盖、QC 门禁和混合 Glossary/body 策略。 (~2600 tok)
- `docs/SHORT_VIDEO_QWEN_WORKFLOW_DESIGN_20260527.md` — Qwen 短视频批量抽取工作流设计；定义 preprocess-only、synthesize-only、packing、VIDEO_ID 拆分、短视频 QC、CLI 和 P0-P3 实施阶段。 (~7600 tok)
- `docs/TOUTIAO_FAVORITES_RUNBOOK.md` — 今日头条收藏夹同步运行手册；说明登录态保存、收藏页探测、manifest 更新、下载到 Videos/short/toutiao 以及接短视频 pipeline 的命令。 (~2500 tok)
- `docs/WIN_TOUTIAO_MISSING_PAYLOAD_HANDOFF_20260529.md` — WIN 执行交接：重建收藏队列、用移动 Playwright 捕获 Toutiao/Toutiaovod mp4、批量处理 18 missing_payload、preprocess 与停止条件。 (~4300 tok)
- `LIVE_FINAL_QUALITY_ROADMAP.md` — Live Final Quality Roadmap (~3188 tok)

## githooks/


## runs/

- `runs/stream-replay-ab-20260526-20260526-145918.gemini35.final-qc.json` — Gemini A/B final QC；source_status=partial、frame_count=0、body_coverage_status=ok、body_tail_gap_s=58。 (~500 tok)
- `runs/stream-replay-ab-20260526-20260526-145918.qwen.final-qc.json` — Qwen A/B final QC；source_status=partial、frame_count=0、body_coverage_status=ok、body_tail_gap_s=60，记录 Qwen usage 40,325 tokens。 (~600 tok)

## scripts/

- `build_stream_markdown.py` — Post-stream LLM synthesis: assemble all live chunks → NotebookLM document. (~25718 tok)
- `live_sectioned_synthesis.py` — P1 Sectioned Synthesis: three-pass pipeline for live-stream final documents. (~30063 tok)
- `merge_stream_chunks.py` — parse_chunk_start, parse_timestamp, load_chunk_lines, load_chunk_slides (~2020 tok)
- `scripts/build_stream_markdown.py` — P0 live final synthesis入口；支持 Gemini/Qwen one-shot、Qwen `--synthesis-pass sliding-window` 窗口 notes+最终组装、final-qc/body/Qwen NotebookLM QC、预算 dry-run，并确定性追加完整逐字稿/视觉证据索引。 (~12000 tok)
- `scripts/check_auth.py` — 鉴权检查工具。 (~80 tok)
- `scripts/live_sectioned_synthesis.py` — P1-P2 分层合成主模块。新增 `run_full_pipeline()` 公共入口（Fix1）。Fix2: evidence hash 含 cleaned_transcript+frame type/ts+stale传播。Fix3: slide边界 frame key 归一化。Fix4: 术语词边界。 (~23000 tok)
- `scripts/merge_stream_chunks.py` — 合并 stream chunk 文件。 (~300 tok)
- `scripts/short_video_pipeline.py` — P0 Qwen 短视频批量入口；支持 preprocess 生成 payload、synthesize --dry-run 装包计划、status 和 mock-payloads 离线验证，不调用 Qwen API。 (~7200 tok)
- `scripts/terminology.json` — 项目术语表，9 条规则（Claude Code/RAG/MCP 等），供 normalize_transcript 使用。 (~60 tok)
- `scripts/toutiao_common.py` — 今日头条收藏同步公共工具；定义 cache/auth/manifest/video 路径、URL/ID 规范化、manifest merge、Playwright context 和 storage_state 到 yt-dlp cookie 转换。 (~3300 tok)
- `scripts/toutiao_classify_favorites.py` — 今日头条收藏夹通用分类探测器；使用登录态打开收藏页、滚动抓取收藏卡片、按 video/article/image/audio/text/mixed/unknown 初判，并输出 JSON/Markdown 报告，可选更新 manifest。 (~7600 tok)
- `scripts/toutiao_build_source_cards.py` — 从今日头条分类报告生成 metadata-only source-card Markdown；按 item 写入 `Markdowns/source_cards/toutiao/`，记录来源、分类、封面、摘要、下载状态和下一步摄取策略。 (~3300 tok)
- `scripts/toutiao_download_favorites.py` — 从 cache/toutiao/manifest.json 下载今日头条收藏视频；优先 yt-dlp，失败后 Playwright 捕获媒体 URL + ffmpeg，落盘 Videos/short/toutiao。 (~3000 tok)
- `scripts/toutiao_export_missing_payload_queue.py` — 从 reconcile JSON 导出当前 missing_payload 独立处理队列，结合 classify JSON 回填视频时长，输出 JSON/Markdown/URL list 供定向下载实验。 (~2600 tok)
- `scripts/toutiao_login.py` — 打开 Playwright 有头浏览器登录今日头条，并保存登录态到 cache/toutiao/auth_state.json。 (~700 tok)
- `scripts/toutiao_probe_media_candidates.py` — 针对 missing_payload 队列逐 URL 变体抓取移动/桌面页面、网络响应、GetPlayInfo/video_mp4 线索和 app-gate 文案，输出 JSON/Markdown 取证报告。 (~6500 tok)
- `scripts/toutiao_probe_favorites.py` — 使用 Playwright 登录态打开今日头条收藏页、滚动探测视频链接/网络候选项，可写 probe JSON、screenshot 并更新 manifest。 (~2700 tok)
- `scripts/toutiao_reconcile_favorites.py` — 对齐当前 `cache/toutiao/manifest.json` 收藏项与历史 `runs/short-video/preprocess` payload、`Markdowns/TTS_short_*.md` 成品，输出缺口/已完成/历史-only 报告。 (~4100 tok)
- `scripts/toutiao_update_source_cards_from_reconcile.py` — 根据 reconcile JSON 给 `Markdowns/source_cards/toutiao/*.md` 追加/替换对齐状态区块，标明已有 Markdown、payload、缺口和下一步动作。 (~2100 tok)
- `short_video_pipeline.py` — class: load_sv_progress, save_sv_progress, update_sv_video, estimate_cost_cny + 14 more (~16086 tok)
- `toutiao_common.py` — from: now_iso, ensure_dirs, slugify, sha1_short + 11 more (~2113 tok)
- `toutiao_download_favorites.py` — stream_extractors lives in the repo root, not in scripts/; ensure it's importable (~1888 tok)
