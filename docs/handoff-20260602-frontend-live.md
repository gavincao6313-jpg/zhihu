# 前端直播流水线 — 完整问题链与修复记录

> **日期**: 2026-06-02 | **直播**: 19:50-21:30 (86 分钟, 87 chunks)
> **From**: Windows Run Owner → **To**: Mac Code Owner

---

## 一、启动前：前端 Launch 按钮报错 (17:22 - 17:42)

### 1.1 回放 URL 测试暴露的 4 层 Bug

用户在前端测试回放 URL，点击"启动"连续失败。

| 层 | 错误 | 根因 | 修复 Commit |
|:--:|------|------|------|
| 1 | `unrecognized arguments: --base --runs-dir` | `launch_replay_pipeline` 传了 `zhihuTTS_stream.py` 不认的参数 | `7b11559` `--base`→`--name` |
| 2 | `ffprobe: 403 Forbidden` | 知乎页面 URL 用 `--url` 当媒体文件喂给 ffprobe | `205b1fc` `--url`→`--page-url` + playwright |
| 3 | `ffprobe: range: bytes=21757952-` | 浏览器 `Range` 头原样传给 ffprobe，CDN 拒绝 | `5b5900a` `build_ffmpeg_headers()` 过滤 8 个不安全头 |
| 4 | 日志显示 ANSI 乱码 | tqdm 进度条的 `\x1b[34m` `\r` 等控制字符 | `7dc2553` 服务端正则过滤 |

### 1.2 回放路径最终验证

17:42 回放全流程跑通：Playwright 提取 → ffmpeg 切片 → SenseVoice 转写 → Qwen 合成 → 前端展示 ✅

---

## 二、直播启动：第一次失败 (19:50)

### 2.1 现象

用户在前端粘贴直播间 URL，选择 Live → 点击"启动" → 立即报错。

### 2.2 错误日志

```
zhihuTTS_stream.py: error: unrecognized arguments: --continuous-hls --base-marker
```

### 2.3 根因

`launch_live_pipeline` 使用了 `feature/stream-transcript-validation` 分支的参数（`--continuous-hls`、`--base-marker`），但 main 分支的 `zhihuTTS_stream.py` 没有这些参数。

Mac 合并 feature 分支到 main 时，这些参数没有被合并过来。main 分支的直播模式走的是 `run_validation()` 函数，用 `--playwright-keepalive --duration 0` 触发无限录制。

### 2.4 修复 (Commit `a78edcf`)

```python
# 废弃（feature 分支参数，main 不存在）
"--continuous-hls", "--base-marker", str(marker_file),

# 改为（main 分支实际支持的）
"--playwright-keepalive",
"--page-url", source,
"--playwright-storage-state", str(auth),
"--duration", "0",        # 0 = 直播模式
"--chunk-duration", "60",
"--name", captured_name,
```

### 2.5 问题

`--continuous-hls` 和 `--base-marker` 是 feature/stream-transcript-validation 的功能，包含独立的 Recorder/Consumer 线程架构和分片合并机制。main 分支用 `run_validation()` 的 live_mode 替代。

**Mac 需要确认**: feature 分支的 `run_continuous_hls` 是否需要合并到 main？两个实现的功能差异是什么？

---

## 三、直播进行中：日志乱码 (19:53 - 21:30)

### 3.1 现象

前端 Logs Tab 显示 `100%|�������� | rtf_avg: 15.264` 等乱码。

### 3.2 根因

`_run_pipeline_engine` 只做了 `_ANSI_RE.sub("", line)` 过滤 ANSI CSI 序列，但 tqdm 还有 `\r` 回车重写、进度条方块字符等控制字符没清理。

### 3.3 修复 (Commit `2930597`)

```python
# 激进清理：只保留可打印字符
line = _ANSI_RE.sub("", line)
line = "".join(ch for ch in line if ch.isprintable() or ch in "\n\t")
```

### 3.4 注意

修复推送后 API 未重启（直播运行中不能杀进程），所以本次直播的日志仍然是乱码。下次直播生效。

---

## 四、转写完成后：API 挂掉 + Registry 孤悬记录 (21:36)

### 4.1 现象

直播在 21:30 左右结束，87 chunks 全部转写完成，Gemini 合成在 21:36:17 生成 187KB Markdown。

但用户在前端看不到任何进展：
- 前端列表显示 `status: failed`，更新时间停在 `19:50:31`
- Logs Tab 停在 "Sending to Gemini (1148 parts)..."
- 实际的 completed 产物在列表里不显示

### 4.2 根因 A：API 进程挂掉

**竞态条件**:

```
Pipeline daemon 线程                    HTTP 轮询线程 (每 5s)
─────────────────────                   ─────────────────────
update_registry_record()
  → write_json(registry_path) ──┐
                                ├──→ list_registry_records()
                                │      → read_json(registry_path)
  → (写入中，文件不完整) ───────┘      → JSONDecodeError
                                       → HTTP 500
                                       → 累积崩溃
```

`write_json` 不是原子操作。Pipeline 线程写 JSON 文件时，HTTP 线程同时读，读到半截文件 → JSON 解析失败 → 线程异常。多次累积后 `ThreadingHTTPServer` 不再响应。

### 4.3 根因 B：Registry 孤悬记录

```
第一次启动 (19:50) → --continuous-hls 报错 → status="failed" → 记录留在 registry
第二次启动 (19:53) → 创建新记录 → 成功 → cleanup 删除新记录
                                            ↓
                              旧 "failed" 记录还在！
                              前端列表一直显示这条 failed 记录
```

逻辑链：
1. `launch_live_pipeline` 只有 `if ok: _remove_registry_record()` —— 失败不清理
2. 每次从前端点击"启动"都创建**新** registry 记录（新 ID）
3. 旧失败记录无人清理，永久残留

### 4.4 修复 (Commit `1be5769`)

**A. 线程安全**:
```python
_REGISTRY_LOCK = threading.Lock()

def save_registry_record(record):
    with _REGISTRY_LOCK:      # ← 加锁
        write_json(...)

def update_registry_record(...):
    with _REGISTRY_LOCK:      # ← 加锁
        write_json(...)

def _remove_registry_record(...):
    with _REGISTRY_LOCK:      # ← 加锁
        write_json(...)
```

**B. 旧记录自动清理**:
```python
def _cleanup_orphaned_records(new_url: str) -> None:
    """启动前删除相同 URL 的旧 failed/created 记录"""
    ...

def launch_live_pipeline(...):
    _cleanup_orphaned_records(source)  # ← 新增
    ...
```

---

## 五、提交链总览

| Commit | 时间 | 修复 |
|--------|------|------|
| `7b11559` | 17:28 | `--base`/`--runs-dir` → `--name` |
| `205b1fc` | 17:30 | `--url` → `--page-url` + playwright |
| `5b5900a` | 17:36 | ffmpeg headers 过滤 Range 等 8 个头 |
| `7dc2553` | 17:38 | ANSI 转义码清理 + 等宽字体 |
| `a78edcf` | 19:52 | `--continuous-hls` → main 分支兼容 |
| `2930597` | 20:05 | 激进控制字符清理（未重启） |
| `1be5769` | 21:50 | 线程锁 + 孤悬记录自动清理 |

---

## 六、产物确认

| 产物 | 详情 |
|------|------|
| Chunks | 87 个 (86 分钟) |
| Combined Transcript | 85KB |
| Manifest | manifest.json + manifest.md |
| Gemini Markdown | 187KB `TTS_stream-live-20260602-195306-gemini.md` |
| QC | gemini.final-qc.json |
| 前端可见 | ✅ `/api/runs` 返回 completed 状态 |

---

## 七、Mac 端建议

| 优先级 | 行动 |
|:--:|------|
| P1 | 合并 `feature/stream-transcript-validation` 的 `--continuous-hls` 到 main，或确认 main 的 `run_validation` live_mode 已覆盖所有场景 |
| P1 | `launch_live_pipeline` 成功后只生成了 Gemini，未生成 Qwen 对比。是设计意图还是遗漏？ |
| P2 | API + 前端进程守护（`start_win.bat` 崩溃后自动重启） |
| P2 | `_resolve_run_base()` 在 chunk 文件延迟出现时可能返回 hint（fallback），导致 merge 找不到文件 |
| P3 | Launch 按钮增加二次确认（避免误触发起重复直播） |
| P3 | `_run_pipeline_engine` 的 `log_every_n=15` 在 tqdm 密集输出时每 15 行 flush 一次，导致日志显示滞后。建议改为时间驱动 flush（每 5 秒） |

---

> 🤖 Windows Run Owner | 2026-06-02
