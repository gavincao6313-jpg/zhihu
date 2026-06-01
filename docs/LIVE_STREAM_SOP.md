# 知乎直播转写标准操作流程 (SOP)

> **状态**: 生产就绪 | **最后验证**: 2026-06-01 | **版本**: v1.0
>
> 本文档是启动知乎 CC / 小鹅通直播转写的**唯一权威流程**。禁止凭记忆或聊天上下文操作。

---

## 一、前置检查（必须逐项确认）

### 1.1 环境检查

```powershell
# 在 PowerShell 中逐项执行，全部 OK 才能继续

# 1. venv
Test-Path "d:\zhihu\zhihu_file\.venv-sensevoice\Scripts\python.exe"
# 期望: True

# 2. ffmpeg
Get-Command "ffmpeg" -ErrorAction SilentlyContinue
# 期望: 显示 ffmpeg 路径

# 3. 认证文件
(Get-Item "d:\zhihu\zhihu_url\zhihu_auth_state.json").Length
# 期望: > 1000 bytes（知乎 CC）
# 小鹅通: zhihu_auth_state_xiaoe.json

# 4. API Key（如需 AI 笔记生成）
$env:GEMINI_API_KEY   # Gemini: 已设置
$env:DASHSCOPE_API_KEY # Qwen: 已设置
```

### 1.2 认证有效性检查

```powershell
Set-Location d:\zhihu\zhihu_url
& "d:\zhihu\zhihu_file\.venv-sensevoice\Scripts\python.exe" "scripts\check_auth.py" "zhihu_auth_state.json" --platform "zhihu"
# 期望输出: [auth] z_c0 cookie valid, ~XXXh remaining
```

如果认证失败，重新登录：
```powershell
& "d:\zhihu\zhihu_file\.venv-sensevoice\Scripts\python.exe" "login_save_auth.py"
```

### 1.3 分支检查

```powershell
Set-Location d:\zhihu\zhihu_url
git branch --show-current
# 直播转写必须使用: feature/stream-transcript-validation
# 如果不在该分支:
git stash
git switch feature/stream-transcript-validation
git pull --ff-only
```

---

## 二、启动流水线

### 2.1 核心命令（唯一正确方式）

```powershell
# ⚠️ 必须使用此精确命令格式！其他变体已被验证会失败！

$url = '<直播间URL>'  # 替换为实际 URL
$workDir = 'd:\zhihu\zhihu_url'

# 使用 Start-Process + cmd /c 创建完全独立进程
$cmdArgs = '/c ""d:\zhihu\zhihu_url\run_zhihu_live.bat" "' + $url + '" --no-gemini"'
Start-Process -FilePath "cmd.exe" -ArgumentList $cmdArgs -WindowStyle Hidden -WorkingDirectory $workDir
```

### 2.2 为什么必须这样启动

| 错误方式 | 问题 |
|----------|------|
| `.\run_zhihu_live.bat "URL"` 直接在 PowerShell | URL 中的 `?is_hybrid=1` 被 cmd 解析为多个参数 |
| `cmd /c "run_zhihu_live.bat URL"` (无外层引号) | `&` 或特殊字符导致参数截断 |
| `Start-Process` 用 `-ArgumentList` 数组 | PowerShell 5.1 的引号转义不可靠 |
| 包在 PowerShell 背景任务中 | 任务停止会杀掉整个进程树 |

**正确方式**: `Start-Process -WindowStyle Hidden` + `cmd /c` + 外层双引号包裹整个命令，创建**完全独立**的进程树，不受 PowerShell 会话影响。

### 2.3 Provider 选择

| 模式 | 参数 | 说明 |
|------|------|------|
| 仅转录（推荐） | `--no-gemini` | 先转录，后手动跑双模型合成 |
| Gemini 合成 | `--provider gemini` | 转录后自动用 Gemini 生成笔记 |
| Qwen 合成 | `--provider qwen` | 转录后自动用 Qwen 生成笔记 |
| 干运行 | `--dry-run` | 仅打印计划，不执行 |

---

## 三、验证流水线运行

### 3.1 30 秒后确认启动成功

```powershell
# 检查进程（期望: Python x2 + ffmpeg x1）
Get-Process -Name "python","ffmpeg" -ErrorAction SilentlyContinue

# 查看最新日志
Get-ChildItem "d:\zhihu\zhihu_url\logs" -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | ForEach-Object {
    Write-Output "=== $($_.Name) ==="
    Get-Content $_.FullName -Tail 10 -Encoding UTF8
}
```

**成功标志**（日志中必须出现）:
```
=== HLS Continuous mode ===
Name    : live_YYYYMMDD_<页面标题>
Work dir: ...\.stream\live_YYYYMMDD_...\...
Chunk   : 60.0s
[Recorder] Session XXXXXXXXXX → ...\seg_XXXXXXXXXX_%06d.ts
```

### 3.2 持续验证（5 分钟后）

```powershell
# 检查是否有 TS 文件和转录报告产出
$workDir = Get-ChildItem "d:\zhihu\zhihu_url\Videos\.stream" -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
(Get-ChildItem $workDir.FullName -File -Filter "*.ts").Count  # 应 >= 1

Get-ChildItem "d:\zhihu\zhihu_url\runs\stream-live_*chunk*" -File -Filter "*.md" | Sort-Object Name
# 应看到 chunk 报告
```

---

## 四、直播结束后操作

### 4.1 确认直播已结束

日志中出现以下任一标志：
- `[Recorder] DOM confirms stream ended.`
- `直播已结束`
- `StreamEndedError`
- `stream_ended_reason`

### 4.2 查看输出文件

```powershell
# 找到 base marker
Get-Content "d:\zhihu\zhihu_url\runs\stream-base-live-*.txt" -Encoding UTF8
# 返回: live_YYYYMMDD_<标题>

# 列出所有 chunk
Get-ChildItem "d:\zhihu\zhihu_url\runs\stream-live_*chunk*.md" | Sort-Object Name
```

### 4.3 双模型 A/B 合成

```powershell
$base = "live_YYYYMMDD_<标题>"  # 从 base marker 获取
Set-Location d:\zhihu\zhihu_url\scripts

# Gemini 合成
& "d:\zhihu\zhihu_file\.venv-sensevoice\Scripts\python.exe" "build_stream_markdown.py" `
  --base $base --provider gemini --output-label gemini35 `
  --runs-dir "..\runs" --markdowns-dir "..\Markdowns"

# Qwen 合成（公平对比: 128 帧）
& "d:\zhihu\zhihu_file\.venv-sensevoice\Scripts\python.exe" "build_stream_markdown.py" `
  --base $base --provider qwen --output-label qwen --max-frames 128 `
  --runs-dir "..\runs" --markdowns-dir "..\Markdowns"
```

---

## 五、🚫 绝对禁止的操作

| 禁止操作 | 后果 | 正确做法 |
|----------|------|----------|
| **杀掉 ffmpeg 进程** | Playwright 刷新 URL 时浏览器崩溃，整个流水线中断 | 等待 ffmpeg 自然退出或 Recorder 自动处理 |
| **杀掉 python 进程** | 转写数据丢失 | 等待直播自然结束或 Ctrl+C |
| **关闭启动用的 PowerShell 窗口** | 不影响（进程已独立） | — |
| **在流水线运行中修改代码或切换分支** | 不可预测 | 等直播结束后再操作 |
| **同时启动两个相同 URL 的流水线** | 两份 TS 文件，合并复杂 | 确认只有一个实例在运行 |

### 5.1 ffmpeg 看起来"卡住了"怎么办？

**ffmpeg CPU 不增长是正常现象！** FLV 流可能暂时没有数据（老师暂停/网络波动），但 TCP 连接仍然存活。ffmpeg 的 `-reconnect` 参数会自动处理重连。

- ❌ 不要杀 ffmpeg
- ✅ 等待 3-5 分钟再检查 TS 文件数量是否增长
- ✅ 如果超过 10 分钟没有新 TS 文件，检查日志 `[Recorder]` 行

---

## 六、常见故障处理

### 6.1 启动时报 "未截获流媒体"

**原因**: 老师尚未进入教室，页面没有直播流。

**处理**:
```powershell
# 等待 1-2 分钟后重试。如果持续失败超过 10 分钟，检查：
# 1. URL 是否正确（是否已过期/变更）
# 2. 认证是否有效
# 3. 手动在浏览器打开 URL，确认直播间状态
```

### 6.2 流水线中途崩溃

**原因**: Playwright 浏览器崩溃（内存不足、页面被关闭等）。

**处理**:
```powershell
# 1. 清理残留进程
Get-Process -Name "python","ffmpeg","chromium" -ErrorAction SilentlyContinue | Stop-Process -Force

# 2. 检查已有 chunk（数据已保存）
Get-ChildItem "d:\zhihu\zhihu_url\runs\stream-live_*chunk*.md" | Sort-Object Name

# 3. 重新启动流水线（使用同一 URL）
# 新会话会从当前时间点继续录制
```

### 6.3 磁盘空间不足

```powershell
# 直播期间每小时约消耗:
# TS 文件: ~100 MB/h (取决于码率)
# 转录缓存: ~10 MB/h
# 总需求: 建议保持 5GB 以上可用空间

# 检查
$drive = (Get-Item "d:\").PSDrive
Write-Output "剩余: $([math]::Round($drive.Free/1GB, 1)) GB"
```

---

## 七、输出物清单

一次完整直播运行产生以下文件：

```
runs/
  stream-<NAME>-<TIME>.combined-transcript.txt    # 完整逐字稿
  stream-<NAME>-<TIME>.manifest.md                 # 逐块统计
  stream-<NAME>_chunkXXX_*.md                      # 各分块报告
  stream-<NAME>_chunkXXX_*.transcript.txt          # 各分块转写

Markdowns/
  TTS_stream-<NAME>-gemini35.md                    # Gemini NotebookLM 笔记
  TTS_stream-<NAME>-qwen.md                        # Qwen NotebookLM 笔记

Slides/
  <NAME>/slides.pdf + slides.pptx                  # 幻灯片

logs/
  run-<NAME>.log                                   # 完整运行日志
```

---

## 八、快速参考卡片

```powershell
# === 启动直播转写（复制粘贴，替换 URL）===
$url = '<PASTE_URL_HERE>'
$workDir = 'd:\zhihu\zhihu_url'
$cmdArgs = '/c ""d:\zhihu\zhihu_url\run_zhihu_live.bat" "' + $url + '" --no-gemini"'
Start-Process -FilePath "cmd.exe" -ArgumentList $cmdArgs -WindowStyle Hidden -WorkingDirectory $workDir
# 等待 30 秒后执行验证步骤

# === 验证运行 ===
Get-Process -Name "python","ffmpeg" -ErrorAction SilentlyContinue
Get-ChildItem "d:\zhihu\zhihu_url\logs" -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | ForEach-Object { Get-Content $_.FullName -Tail 5 -Encoding UTF8 }

# === 查看进度 ===
Get-ChildItem "d:\zhihu\zhihu_url\runs\stream-live_*chunk*.md" | Sort-Object Name | Select-Object -Last 5
```

---

> **维护责任**: Windows Run Owner
> **关联文档**: `BRANCH_USAGE.md`, `WINDOWS_RUNBOOK.md`, `memory/project_zhihu_live_pipeline.md`
