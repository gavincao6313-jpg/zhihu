# anatomy.md

> Auto-maintained by OpenWolf. Last scanned: 2026-05-22T11:41:41.186Z
> Files: 16 tracked | Anatomy hits: 0 | Misses: 0

## ./

- `CLAUDE.md` — OpenWolf (~1508 tok)
- `run_single_file.py` — Run zhihuTTS file pipeline on a single video for A/B testing. (~280 tok)
- `run_zhihu_live.bat` (~2276 tok)

## .claude/


## .claude/rules/

- `review.md` — AI 审查工作流 (~348 tok)

## .wolf/

- `anatomy.md` — File navigation index for the current workspace. (~164 tok)
- `OPENWOLF.md` — OpenWolf session protocol and memory rules. (~1638 tok)

## C:/Users/Admin/.claude/projects/D--zhihu-zhihu/memory/


## C:/Users/Admin/AppData/Local/Temp/whisper-src/whisper_cpp_python-0.2.0/


## C:/Users/Admin/AppData/Roaming/Python/Python314/site-packages/whisper_cpp_python/


## Markdowns/


## docs/

- `docs/LIVE_FINAL_QUALITY_ROADMAP.md` — 直播流质量提升路线图，P0→P1→P2，18个带验证标准的 checkbox 任务，进度表。 (~2800 tok)
- `docs/LIVE_STREAM_OPTIMIZATION_BACKLOG_20260521.md` — 旧版问题 backlog，已被 ROADMAP 取代。 (~100 tok)
- `LIVE_FINAL_QUALITY_ROADMAP.md` — Live Final Quality Roadmap (~2855 tok)

## githooks/


## runs/


## scripts/

- `build_stream_markdown.py` — Post-stream Gemini synthesis: assemble all live chunks → NotebookLM document. (~4910 tok)
- `live_sectioned_synthesis.py` — P1 Sectioned Synthesis: three-pass pipeline for live-stream final documents. (~30063 tok)
- `scripts/build_stream_markdown.py` — P0 一键合成入口，新增 `--sectioned` 路由至 P1 三段合成（Fix1）。Fix5: `tail_coverage_low` 纳入 `source_status` 判断。 (~4910 tok)
- `scripts/check_auth.py` — 鉴权检查工具。 (~80 tok)
- `scripts/live_sectioned_synthesis.py` — P1-P2 分层合成主模块。新增 `run_full_pipeline()` 公共入口（Fix1）。Fix2: evidence hash 含 cleaned_transcript+frame type/ts+stale传播。Fix3: slide边界 frame key 归一化。Fix4: 术语词边界。 (~23000 tok)
- `scripts/merge_stream_chunks.py` — 合并 stream chunk 文件。 (~300 tok)
- `scripts/terminology.json` — 项目术语表，9 条规则（Claude Code/RAG/MCP 等），供 normalize_transcript 使用。 (~60 tok)
