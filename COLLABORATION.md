# 协作流程

## 共享边界

边界按文件用途划分，不按机器划分。Windows 和 Mac 都遵循同一套准则：

1. 本机专属配置、私有权限、运行环境偏好、本机遥测、缓存和密钥不共享。
2. 项目共识、协作规则、可复现的运行报告、进度状态、最终输出，以及对端需要理解并继续执行的内容要提交到 Git。
3. 代码变更、运行结果、工具状态尽量分开提交，避免混合提交导致职责不清。

详细规则见 `docs/SHARED_STATE_POLICY.md`。

## 文件类别

| 类别 | 共享策略 | 示例 |
|---|---|---|
| 代码与依赖 | 提交 | `.py`, `requirements.txt` |
| 协作规则与运行手册 | 提交 | `AGENTS.md`, `CLAUDE.md`, `COLLABORATION.md`, `docs/*.md` |
| 共享工具定义 | 提交 | `githooks/**`, `.claude/settings.json`, `.claude/rules/**`, `.wolf/OPENWOLF.md`, `.wolf/config.json`, `.wolf/hooks/**` |
| 项目记忆与共识 | 提交 | `.wolf/anatomy.md`, `.wolf/cerebrum.md`, `.wolf/memory.md`, `.wolf/buglog.json` |
| 进度与最终输出 | 提交 | `.progress.json`, `Markdowns/*.md`, `runs/*.md` |
| 原始日志和本机遥测 | 不提交 | `*.log`, `.wolf/hooks/_session.json`, `.wolf/token-ledger.json` |
| 本地缓存和生成索引 | 不提交 | `Videos/**`, `cache/**`, `.gitnexus/**`, `graphify-out/**` |

## 开始前

两边开始 Codex 会话前都应先同步仓库并阅读本文：

```bash
git pull --rebase
```

如果本地有未提交改动，先按文件用途确认是否应该共享，再继续。

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

仓库内 `githooks/pre-commit` 会拦截本机产物、遥测、缓存、密钥文件，以及代码/协作文档和运行结果混合提交。两台机器都需要执行一次：

```bash
git config core.hooksPath githooks
```

如果确实需要例外：

```bash
SKIP_ROLE_CHECK=1 git commit ...
```
