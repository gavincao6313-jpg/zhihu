# 协作流程

## 角色边界

| 角色 | 常用机器 | 职责 | 可提交内容 |
|---|---|---|---|
| Code Owner | Mac | 代码、依赖、hook、架构和协作文档 | `.py`, `requirements.txt`, `.gitignore`, `.gitattributes`, `githooks/`, `docs/`, `COLLABORATION.md` |
| Run Owner | Windows | 跑批、检查日志、提交进度和生成结果 | `.progress.json`, `Markdowns/TTS_*.md`, `runs/*.md` |

边界按职责划分，不按机器能力划分。Windows Codex 可以分析代码问题，但代码修复应形成说明、issue 或 handoff，由 Code Owner 修改。

## 开始前

两边开始 Codex 会话前都应先同步仓库并阅读本文：

```bash
git pull --rebase
```

如果本地有未提交改动，先确认它们属于自己的职责范围，再继续。

## Code Owner 规则

- 不修改、不提交 `.progress.json`。
- 可修改代码、依赖、hook、`.gitignore`、`.gitattributes`、架构文档和 runbook。
- 修改 Python 符号前按 `AGENTS.md` 使用 GitNexus 做影响分析；提交前使用 GitNexus 检查变更影响。
- 不提交运行时大文件或本地缓存。

## Run Owner 规则

- 负责运行批处理、观察日志、提交处理进度和生成 Markdown。
- 可以提交 `.progress.json`、`Markdowns/TTS_*.md`、`runs/*.md`。
- 不修改 `.py`、依赖文件、hook、repo 配置或架构文档。
- 如果发现代码缺陷，提交复现信息、日志摘要或文档交接，不直接 patch 代码。

## Windows 日常运行

```bash
git pull --rebase
python zhihuTTS.py --status
python zhihuTTS.py
git status
git add .progress.json Markdowns/TTS_*.md runs/*.md
git commit -m "run: YYYY-MM-DD batch results"
git push
```

## Mac 日常开发

```bash
git pull --rebase
# ... 修改代码/文档/hook ...
python -m py_compile zhihuTTS.py zhihuTTS_video.py
git status
git add zhihuTTS.py zhihuTTS_video.py requirements.txt .gitignore COLLABORATION.md docs/ githooks/
git commit -m "perf: add whisper.cpp CLI backend"
git push
```

## 环境变量

| 变量 | 说明 |
|---|---|
| `OPENCLAW_GOOGLE_API_KEY` | Gemini API 密钥，运行主流程必填 |
| `GEMINI_BASE_URL` | 可选 Gemini 代理地址 |
| `GEMINI_API_VERSION` | 使用代理时的 API 版本，默认 `v1beta` |
| `WHISPER_BACKEND` | `auto`, `cpu`, `whispercpp-vulkan` |
| `WHISPER_CPP_EXE` | 外部 `whisper-cli.exe` 路径 |
| `WHISPER_CPP_MODEL` | whisper.cpp ggml 模型路径 |
| `WHISPER_BEAM_SIZE` | faster-whisper beam size，默认 `1` |
| `WHISPER_WORD_TIMESTAMPS` | 是否生成词级时间戳，默认 `0` |
| `WHISPER_CPU_THREADS` | faster-whisper CPU 线程数，默认 `0` 自动 |
| `WHISPER_CPU_WORKERS` | faster-whisper worker 数，默认 `4` |

## Git Hook

仓库内 `githooks/pre-commit` 会拦截职责外提交和大运行产物。两台机器都需要执行一次：

```bash
git config core.hooksPath githooks
```

如果确实需要例外：

```bash
SKIP_ROLE_CHECK=1 git commit ...
```
