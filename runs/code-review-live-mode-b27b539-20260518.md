# Live Mode Code Review — b27b539

Date: 2026-05-18
Reviewed: becc73c → b27b539 (`fix: resolve 6 live-mode bugs found in retrospective review`)

## 更新验证

b27b539 修复了 6 个问题，对照上次 review 的 5 项建议：

| 上次建议 | 状态 | 说明 |
|----------|------|------|
| manifest 增量写入 | ⚠️ 未修复 | 仍是最后一次性写。但 Ctrl-C 和 StreamSliceError 现在会走到 manifest 写入路径 |
| chunk_index -= 1 位置 | ✅ 已修复 | 移入 `finally` 块，重启失败也重试 |
| 空切片生成多余文件 | ❌ 未修复 | 静音 chunk 仍输出 4 个几乎为空的文件 |
| MAX_BROWSER_RESTARTS 硬编码 | ❌ 未修复 | 仍是 `= 3` |
| restart() 状态一致性问题 | ❌ 未修复 | `close()` 抛异常后 `start()` 失败时状态不确定 |

另外发现的新增优化：
- `page.content()` → `innerText`：DOM 检测更快更轻量
- candidate list 上限 200：解决长直播内存泄漏
- YTDLP_ENDED_PATTERNS 收紧：减少假阳性导致的误退出
- `StreamSliceError` 顶层捕获：不再因永久切片失败而丢失进度
- `KeyboardInterrupt` 捕获：Ctrl-C 后保存 manifest

---

## 本地运行数据支撑剩余问题

### 问题 1：串行架构 — CPU 闲置 85%

**数据来源**：`runs/stream-bilibili-live-30min_chunk*` (2026-05-18, 28 chunks × 60s)

```
SenseVoice 总转写时间:     301.2s   (avg 10.8s/chunk)
实际 wall clock 总耗时:    2070s    (34.5 min)
估计网络下载 + 帧提取耗时: 1768.8s  (85.4%)
CPU 有效工作占比:          14.6%
```

每个 chunk 的节奏（实测 3 个慢 chunk：83s, 123s, 131s）：
```
|======= 下载 60s =======|==帧==|转写|  → 73.9s avg
                          ↑ CPU 空闲 60s 等网络
```

**对 180 分钟直播的影响**：
- 当前串行：180 × 60s / 60s × 73.9s ≈ **221 分钟** total wall clock
- 如果下载与处理 pipeline 化：前半约 63s/chunk → **189 分钟**，节省 32 分钟

### 问题 2：空转录切片浪费 I/O

**数据来源**：`zhihuTTS_video.py` — SenseVoice VAD 检测后，无语音片段返回 `segments: []`

当前 `process_slice()` 对空切片仍然：
1. `extract_keyframes()` — 提取并分析帧（~3s CPU）
2. 写入 4 个文件到 `runs/`
3. 保留或删除 slice MP4

30 分钟 bilibili 测试恰好全是新闻播报（无静音），但实际直播场景（如游戏直播挂机、讲座中场休息）预计 10-30% 切片为静音。

**180 分钟直播估算**：15% 静音 → 27 个空切片 × (3s keyframes + 4 files I/O + 6.8MB slice) ≈ 80s 浪费 + 184MB slice。

**建议代码位置**：`zhihuTTS_stream.py:471`，在 `transcribe_audio()` 返回后立即判断：
```python
if len(transcript.get("segments", [])) == 0:
    slice_path.unlink(missing_ok=True)
    continue  # 跳过静音切片，不写输出
```

### 问题 3：长直播无 checkpoint

**场景**：180 分钟直播，chunk 150/180 时 Python 进程被 OOM 杀掉或断电。当前只能从头开始。

**建议**：每 N 个 chunk（如每 10 个）将 `(chunk_index, last_successful_time_s, chunks)` 写入临时 checkpoint 文件。添加 `--resume <checkpoint_path>` 参数跳至断点继续。

### 问题 4：MAX_BROWSER_RESTARTS 不可配置

**位置**：`zhihuTTS_stream.py:44`

不同直播平台对浏览器的容忍度不同。知乎直播间可能 30 分钟踢一次，B站可能 2 小时。3 次硬编码对某些场景偏少。

**建议**：添加 `--max-browser-restarts` CLI 参数，默认 3。

---

## 建议优先级

| 优先级 | 建议 | 收益 | 实现复杂度 |
|--------|------|------|-----------|
| **P0** | 空切片跳过处理 | 节省 10-30% I/O + CPU | 低（~5 行） |
| **P0** | checkpoint/resume | 防止长跑数据丢失 | 中 |
| **P1** | manifest 增量写入 | 防止崩溃丢 manifest | 低（~15 行） |
| **P1** | MAX_BROWSER_RESTARTS CLI | 灵活性 | 低（~5 行） |
| **P2** | 下载/处理 pipeline 化 | CPU 利用率 15%→40% | 高（threading 重构） |
| **P2** | restart() 状态一致性 | 防御性编程 | 低（~8 行） |
