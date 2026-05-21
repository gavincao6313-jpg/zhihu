# anatomy.md

> Auto-maintained by OpenWolf. Last scanned: 2026-05-21T13:49:43.852Z
> Files: 58 tracked | Anatomy hits: 0 | Misses: 0

## ./

- `.gitattributes` — Git attributes (~66 tok)
- `.gitignore` — Git ignore rules (~41 tok)
- `.progress.json` (~1155 tok)
- `.wolf/buglog.json` — OpenWolf bug/error log with prior environment and validation issues (~423 tok)
- `CLAUDE.md` — OpenWolf (~57 tok)
- `COLLABORATION.md` — 协作流程 (~321 tok)
- `extract_slides.py` — extract_slides, main (~2128 tok)
- `extract_slides.py` — 从已处理视频提取幻灯片：读 manifest.json 事件 → ffmpeg 高清抽帧 → 去重 → Slides/<stem>/slides.pdf + slides.pptx (~2800 tok)
- `GeminiModelList.py` — 获取 API Key (~275 tok)
- `login_save_auth.py` — Playwright 登录保存知乎认证态到 `zhihu_auth_state.json` (~900 tok)
- `readme` (~3 tok)
- `requirements.txt` — Python dependencies (~19 tok)
- `run_zhihu_live.bat` (~1886 tok)
- `run_zhihu_live.sh` — macOS/Linux live stream runner wrapper for `zhihuTTS_stream.py` (~1800 tok)
- `stream_extractors.py` — Page/live URL extractors: direct/yt-dlp/Playwright plus PlaywrightKeepaliveStream for CC FLV URL interception, browser refresh, stream-end detection, and auth state reuse (~12000 tok)
- `zhihu.code-workspace` (~31 tok)
- `zhihuTTS_stream.py` — StreamSliceError: build_stream_gemini_parts, parse_time, fmt_time (~14341 tok)
- `zhihuTTS_video.py` — analyze_frames, extract_keyframes, requested_transcribe_backend, transcript_backend_matches (~7387 tok)
- `zhihuTTS.py` — tprint, load_progress, save_progress, discover_videos (~8552 tok)

## .claude/

- `settings.json` (~441 tok)

## .claude/rules/

- `openwolf.md` (~313 tok)

## C:/Users/Admin/.claude/projects/D--zhihu-zhihu/memory/

- `MEMORY.md` (~48 tok)
- `pipeline-resume-may15.md` — 当前进度 (~224 tok)
- `project-setup-state.md` — Windows 端配置状态 (~427 tok)

## C:/Users/Admin/AppData/Local/Temp/whisper-src/whisper_cpp_python-0.2.0/

- `setup.py` — WhisperCppFileGen: get_nested_type, print, output, format_ctypes_defs + 6 more (~2594 tok)

## C:/Users/Admin/AppData/Roaming/Python/Python314/site-packages/whisper_cpp_python/

- `whisper.py` — Whisper: from_pretrained, transcribe, translate, format_time (~1997 tok)

## Markdowns/

- `原理_A01_Prompt、Function Calling、RAG_1080P.md` — 原理_A01_Prompt、Function Calling、RAG_1080P (~12409 tok)
- `原理_A02_利用Agent技术让AI像人类一样拆解任务并逐一完成_1080P.md` — 原理_A02_利用Agent技术让AI像人类一样拆解任务并逐一完成_1080P (~13522 tok)
- `原理_A03_预训练＋微调的训练范式 开源生态和 OpenAl的 差异详解_1080P.md` — 原理_A03_预训练＋微调的训练范式 开源生态和 OpenAl的 差异详解_1080P (~10552 tok)
- `原理_A04_探索神经网络的奥秘-1080P.md` — 原理_A04_探索神经网络的奥秘-1080P (~7830 tok)
- `原理_A05_揭秘Transformer的真面目_720P.md` — 原理_A05_揭秘Transformer的真面目_720P (~48039 tok)
- `原理_A06_揭秘Transformer的真面目-1_1080P.md` — 原理_A06_揭秘Transformer的真面目-1_1080P (~7437 tok)
- `原理_A07_揭秘Transformer的真面目-2_1080P.md` — 原理_A07_揭秘Transformer的真面目-2_1080P (~11415 tok)
- `原理_A08_从GPT 到GPT 3.5的华丽升级_720P.md` — 原理_A08_从GPT 到GPT 3.5的华丽升级_720P (~18517 tok)
- `原理_A09_从GPT 到GPT 4 的华丽升级_1080P.md` — 原理_A09_从GPT 到GPT 4 的华丽升级_1080P (~13759 tok)
- `原理_A10_Fine-tuning微调艺术_1080P.md` — 原理_A10_Fine-tuning微调艺术_1080P (~11634 tok)
- `原理_A11_Fine-tuning微调艺术：SFT与RLHF的完美结合_720P.md` — 原理_A11_Fine-tuning微调艺术：SFT与RLHF的完美结合_720P (~15711 tok)
- `原理_A12_多模态领域的Transformer-创意生成的基座原理_1080P.md` — 原理_A12_多模态领域的Transformer-创意生成的基座原理_1080P (~14238 tok)
- `原理_A13_揭开文字、人脸、精密零件、无人驾驶的智能识别面纱_1080P.md` — 原理_A13_揭开文字、人脸、精密零件、无人驾驶的智能识别面纱_1080P (~35702 tok)
- `原理_A14_探索DALL·E、Stable Diffusion如何编织创意图像的魔法_1080P.md` — 原理_A14_探索DALL·E、Stable Diffusion如何编织创意图像的魔法_1080P (~10716 tok)
- `原理_A15_AI视频原理求索-类Sora模型：解锁动态视觉艺术的密码_1080P.md` — 原理_A15_AI视频原理求索-类Sora模型：解锁动态视觉艺术的密码_1080P (~16884 tok)
- `原理_A16_以Llama 和GLM 为首的开源生态追赶OpenAI的真实进程_1080P.md` — 原理_A16_以Llama 和GLM 为首的开源生态追赶OpenAI的真实进程_1080P (~11787 tok)
- `原理_A17_超级引擎：英伟达GPU与CUDA相关的必备知识点_1080P.md` — 原理_A17_超级引擎：英伟达GPU与CUDA相关的必备知识点_1080P (~11565 tok)
- `TTS_0516_产品设计运营_03_【汪源】GenAI的创新逻辑与趋势.md` — 产品设计运营_03 GenAI创新逻辑 (~9000 tok)
- `TTS_0516_产品设计运营_04_【Frank Nee】中国产品如何出海.md` — 产品设计运营_04 中国产品出海 (~14000 tok)
- `TTS_0516_产品设计运营_05_【柯杰】钉钉 AI 助理平台核心技术实践.md` — 产品设计运营_05 钉钉AI助理 (~12000 tok)
- `TTS_0516_产品设计运营_06_【庄稼】水果篮子的启示—如何针对市场端开发和包装人工智能应用.md` — 产品设计运营_06 水果篮子启示 (~10000 tok)
- `TTS_0516_产品设计运营_07_【idoubi】使用 ShipAny 快速开发 AI SaaS 项目.md` — 产品设计运营_07 ShipAny (~8000 tok)
- `TTS_0516_RAG_04_【盛茂家】火山引擎 VikingDB 向量数据库和知识库的实践.md` — RAG_04 火山引擎 VikingDB (~18000 tok)

## docs/

- `BRANCH_USAGE.md` — Branch separation guide for production batch, stream transcript validation, active branch names, commands, and obsolete branch warning (~457 tok)
- `ENGINEERING_HISTORY.md` — Engineering history including 2026-05-17 transcript output and video stream validation branch split (~825 tok)
- `LIVE_STREAM_OPTIMIZATION_BACKLOG_20260521.md` — Saved discussion backlog for URL/live BAT reliability improvements: capture/processing decoupling, runner account, worker mode, resume, URL refresh, diagnostics, and failure classification (~1600 tok)
- `LIVE_STREAM_OPTIMIZATION_PLAN.md` — 直播流优化讨论计划 (~2106 tok)
- `SENSEVOICE_MP4_BACKFILL_CHANGELOG_20260517.md` — Process record for MP4/FUNASR backfill branch change, review checks, pushed commit, and Windows commands (~700 tok)
- `STREAM_AUTOMATION_PLAN_20260517.md` — Discussion record and engineering plan for replacing manual stream URL capture with Python yt-dlp/Playwright extractors and later supervisor logic (~950 tok)
- `WHISPER_BACKEND_IMPROVEMENT_PLAN.md` — Mac/Windows handoff plan for CPU transcription optimization, whisper.cpp CLI Vulkan backend, D-drive temp files, caching, and run reports (~2150 tok)

## githooks/

- `pre-commit` — zhihuTTS 角色检查 hook (~338 tok)

## runs/

- `runs/2026-05-20-MAC-pipeline-verification.md` — branch-only MAC pipeline verification report on `origin/feature/local-transcript-appendix`: 5/9 completed, 4 Mac optimization issues (~1200 tok)
