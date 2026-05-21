# 直播流优化讨论计划

> 记录于 2026-05-21。逐条讨论，讨论完一项在 [ ] 打勾。

---

## P0 — 录流与转写彻底解耦

**状态：[x] 方案已定，待实现**

### 现状问题
当前流程是串行的：抓 60s 片段 → 本地转写/抽帧 → 再抓下一段。
转写/抽帧耗时约 20s 时，这 20s 内没有录流，真实直播会漏内容。

### 已确认：媒体数据路径

```
ffmpeg → CC/FLV URL（直接拉）
Playwright 不在媒体路径上，只负责：
  1. 首次提取 FLV URL
  2. URL 失效时刷新页面重新抓 URL
  3. 通过 DOM 判断直播是否结束
```

### 已确认：完成信号方案

**采用 HLS `temp_file` + 目录监听**（不依赖 m3u8 文件）

- ffmpeg 用 HLS muxer，开 `-hls_flags temp_file`
- ffmpeg 内部流程：写 `seg_xxx.ts.tmp` → 完成后 rename 为 `seg_xxx.ts`
- Consumer 只扫描目录里的 `.ts` 文件（不含 `.tmp`），出现即已完整
- 不读 m3u8：m3u8 在 ffmpeg 重启时会被重写，消费端依赖它会乱序

放弃的方案：
- 轮询文件大小：直播网络抖动时大小短暂稳定，误判率高
- 单一 m3u8 依赖：ffmpeg 重启后 m3u8 被截断重写，processed set 对不上

### 已确认：segment 命名策略

**采用方案 2：session epoch + 局部序号**

```
seg_{session_epoch}_{index:06d}.ts
示例：seg_1716339612_000000.ts
      seg_1716339612_000001.ts   ← 同一次 ffmpeg 运行
      seg_1716340284_000000.ts   ← ffmpeg 重启后，新 session epoch
```

放弃方案 1（supervisor 维护 `next_segment_index`）：需持久化计数器，supervisor 崩溃后仍有命名碰撞风险。
放弃方案 3（session 子目录）：Consumer 需监听多个目录，拼接逻辑复杂。

文件名字典排序 = 录制时间顺序（同 session 内按序号，跨 session 按 epoch 前缀）。

### 已确认：ffmpeg 命令

```bash
ffmpeg \
  -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 3 \
  -headers "<headers>" \
  -i "<flv_url>" \
  -c copy -f hls \
  -hls_time 60 -hls_list_size 0 \
  -hls_segment_type mpegts \
  -hls_flags temp_file \
  -hls_segment_filename "Videos\.stream\seg_{session_epoch}_%06d.ts" \
  "Videos\.stream\seg_{session_epoch}_capture.m3u8"
```

关键决策：
- `-reconnect_delay_max 3`（不是 5）：URL 过期后不让 ffmpeg 自己重试太久，Python supervisor 更快介入
- 不用 `append_list`：用独立 m3u8（含 session epoch），Consumer 不读 m3u8
- 不用 `delete_segments`：Consumer 处理完之前段不能被 ffmpeg 删除

### 已确认：线程模型（2 线程）

```
主线程
  ├── Recorder（Thread）        ← Playwright URL supervisor + ffmpeg manager 合并
  └── SegmentConsumer（Thread） ← 目录监听 + ffprobe 验证 + SenseVoice + 抽帧 合并

协调：recorder_stopped = threading.Event()
```

**Recorder 职责：**
- 启动 Playwright，首次提取 FLV URL
- 启动 ffmpeg subprocess（HLS 分段写入）
- ffmpeg 退出（非正常）→ Playwright 刷新 URL → 用新 session_ts 重启 ffmpeg
- `is_stream_ended()` 返回 True → 设置 `recorder_stopped` → 退出

**SegmentConsumer 职责：**
- 每 5 秒扫描目录，找出未处理的 `.ts` 文件（过滤 `.tmp`）
- 按文件名排序（= 录制时序）逐个处理
- ffprobe 验证（duration ≥ 10s，有 audio stream）→ SenseVoice → 抽帧 → 写 checkpoint
- 处理失败：log + 跳过（**不**加入 processed set，保留下轮重试机会）
- 退出条件：`recorder_stopped` 已设置 **且** 扫描无新段（防止尾部内容丢失）

**流结束判断权威：**
DOM `is_stream_ended()` 为准，不依赖 ffmpeg returncode（部分直播结束时 FLV 服务器不发 EOS，ffmpeg 超时退出返回非 0）。

### 已确认：checkpoint 格式调整

原 checkpoint 记录 chunk index，新架构改为 filename set：

```json
{
  "processed_segments": [
    "seg_1716339612_000000.ts",
    "seg_1716339612_000001.ts"
  ],
  "failed_segments": {
    "seg_1716339612_000003.ts": {"retries": 1, "last_error": "ffprobe failed"}
  }
}
```

### 已确认：函数复用边界

#### 原样复用（签名不变）

| 函数 | 位置 | 说明 |
|------|------|------|
| `PlaywrightKeepaliveStream` | `stream_extractors.py` | 接口基本不变，`refresh()` 已有 |
| `ExtractedStream` | `stream_extractors.py` | 数据类，无需改动 |
| `build_ffmpeg_headers()` | `zhihuTTS_stream.py` | 纯工具函数 |
| `parse_time()` / `fmt_time()` / `safe_name()` | `zhihuTTS_stream.py` | 纯工具函数 |
| `transcribe_audio()` | `zhihuTTS_stream.py` | 内部已用 ffmpeg 转 16kHz WAV，`.ts` 输入理论可直接复用 |
| `extract_keyframes()` | `zhihuTTS_stream.py` | 原样复用 |
| `transcript_to_text()` / `build_gemini_payload()` | `zhihuTTS_stream.py` | 原样复用 |
| `offset_transcript_text()` | `zhihuTTS_stream.py` | 原样复用 |
| `write_report()` / `write_manifest()` | `zhihuTTS_stream.py` | 原样复用 |
| `build_stream_gemini_parts()` | `zhihuTTS_stream.py` | 原样复用 |

#### 拆分（签名扩展）

`process_slice()` → 拆出 `process_segment_file()`：

```python
def process_segment_file(
    segment_path: Path,
    start_s: float,          # 全局时间轴偏移（从 ffprobe 实测累加）
    duration_s: float,       # 来自 ffprobe 实测，不用 hls_time=60
    chunk_index: int,        # 全局 chunk 序号
    base: str,
    runs_dir: Path,
    stream_work_dir: Path,
    gemini_parts: list,
    checkpoint: dict,
    **kwargs,
) -> ChunkRecord:
    ...
```

`process_slice()` 在 Step 1 阶段保持原样调用：先 `slice_url()` → 再调 `process_segment_file()`，行为不变。

#### 淘汰（P0 实现后退役）

- `slice_url()` — 由 ffmpeg HLS 接管
- `process_slice_with_recovery()` — 由 SegmentConsumer 的 skip/retry 替代
- `run_validation()` while 循环 — 由 `Recorder` + `SegmentConsumer` 双线程替代

#### 输出命名兼容

**保持** `stream-{base}_chunk{global_index:03d}_{start_s}s-*` 命名格式，`merge_stream_chunks.py` 和 `build_stream_markdown.py` 无需改动。

---

### 已确认：五个关键技术决策

1. **`.ts` 输入兼容性**：`transcribe_audio()` 内部先将输入用 ffmpeg 转 16kHz mono WAV，理论上 `.ts` 可直接传入。Step 1 完成后作为首个验证点确认。

2. **`duration_s` 来源**：必须用 ffprobe 实测，不能用 `hls_time=60`。尾段、异常短段、网络中断段若按 60s 计算，全局时间轴会漂移。

3. **`start_s` 写入时机**：必须在处理开始前写入 checkpoint（不是处理完成后）。否则转写中途崩溃后 resume 会重新累计时间轴，导致后续 chunk 时间全部漂移。

4. **URL 刷新 gap 处理（方案 A）**：不插入 synthetic chunk。下一个实际录到的 segment 在 manifest 里记录 `gap_before_s` 字段，标注"此前实际丢失了 N 秒录制窗口"。下游时间轴按实际录到的媒体连续走。

5. **Step 1 边界严格控制**：无行为变化重组。只抽出 `process_segment_file()`，旧 `process_slice()` 仍先 `slice_url()` 再调用新函数。Step 1 完成后跑旧模式验证，确认输出结构与之前完全一致，再推进 Step 2。

---

### 实现路径（四步）

| 步骤 | 内容 | 验证方式 |
|------|------|----------|
| Step 1 | 抽出 `process_segment_file()`，`process_slice()` 内调用 | 旧模式跑一次直播回放，输出结构对比 |
| Step 2 | 加 `--continuous-hls` flag，实现 `Recorder` + `SegmentConsumer` 双线程 | 新模式跑一次回放（用本地 `.ts` 文件模拟） |
| Step 3 | 验证 `.ts` → `transcribe_audio()` 路径，确认 gap 记录正确 | 单元验证 + 短直播回放 |
| Step 4 | BAT 加 `set "HLS_FLAG=--continuous-hls"`，切换为连续录制模式 | 完整直播流验证 |

### 待实现（改动边界）

- `zhihuTTS_stream.py`：Step 1 抽 `process_segment_file()`；Step 2 加 `--continuous-hls` 入口
- `stream_extractors.py`：`PlaywrightKeepaliveStream` 接口基本不变，`refresh()` 已有
- checkpoint 格式从 chunk index 迁移到 filename set
- BAT 层：Step 4 加 `HLS_FLAG` 变量，其余不变

---

## P1-A — 专用账号（运营规范）

**状态：[x] 已完成**

### 现状问题
用主账号在另一台机器同时登录直播间，可能被知乎/CC 风控踢下线，代码层无法保证。

### 目标
- Windows 机器用专用账号登录，`zhihu_auth_state.json` 单独维护
- 直播期间不在其他机器用同一账号进直播间
- 跑前预检 Cookie（已有 `check_auth.py`，可扩展检查 `z_c0` 是否存在且非空）

### 已明确
- 代码能做：检测跳登录页 → 日志打 `[账号态失效]`（配合 P2-C）
- 代码不能做：阻止知乎踢下线

### 待讨论
- 专用账号是否已有，还是需要注册新账号？
- `check_auth.py` 是否需要扩展，还是当前预检已够用？

---

## P1-B — BAT 后台 worker 固化 + 窗口说明

**状态：[x] 已完成**

### 现状
当前 BAT 已实现后台 worker 思路（2026-05-21 本 session 完成）：
- 主窗口只 tail 日志，关掉不影响后台任务
- 后台 worker 窗口标题：`zhihu [NAME]`

### 待补充
1. 启动时明确打印区分提示（5 分钟改）：
   ```
   [不要关闭] 后台任务窗口：zhihu [gaowei-20260521]
   [可随时关] 本窗口（日志监控）
   ```
2. 确认是否需要合并到 `feature/stream-transcript-validation` 分支

### 待讨论
- 这版 BAT 是否已经满足需求，还是有其他遗漏场景？
- 是否要在日志里打印 worker 进程 PID（方便 `taskkill`）？

---

## P1-C — Checkpoint Resume

**状态：[x] 已完成**

### 现状
`zhihuTTS_stream.py` 已有 `stream-{base}.checkpoint.json`，但恢复能力不完整。

### 目标
支持：
```bat
run_zhihu_live.bat <URL> <NAME> --resume
```
恢复时从已完成 chunk 后继续，应对：浏览器死、账号失效、机器重启。

### 技术方案（粗）
- BAT 侧：简单透传 `--resume` flag
  ```bat
  if /i "%~3"=="--resume" set "RESUME_FLAG=--resume"
  "!PYTHON!" -u ... !RESUME_FLAG! ...
  ```
- Python 侧：需先确认 checkpoint 能完整描述已完成状态，resume 路径有效

### 待讨论
- `zhihuTTS_stream.py` 的 checkpoint resume 路径是否已可用？
- Resume 后是否从上次 chunk 结束时间开始，还是从上次 chunk 开始时间（有重叠保险）？

---

## P2-A — 流 URL 主动刷新策略

**状态：[x] 已决策，推迟到 P0 Step 2**

### 已确认
- CC `auth_key` TTL ≈ 8h，实际直播 2-4h，**从未遇到过 URL 过期中断**
- 当前被动刷新（`process_slice_with_recovery` → `refresh_and_get()`）已足够保底
- 主动刷新在当前单线程模式收益极小（每 60s 换 chunk 时天然有检查机会）

### 决策
推迟到 **P0 Step 2（Recorder 线程）** 时一并实现。
Recorder 持有 ffmpeg 子进程，主动刷新 = 计时器触发 → `refresh_and_get()` → 重启 ffmpeg（新 session epoch）→ Consumer 记 `gap_before_s`，这才是主动刷新真正有价值的场景。

### 实现位置（待 P0 Step 2）
```python
# Recorder 线程内
PROACTIVE_REFRESH_S = 3600  # 1h，8h TTL 的 1/8
if time.monotonic() - self._url_captured_at > PROACTIVE_REFRESH_S:
    self._restart_ffmpeg(self._keepalive.refresh_and_get(...))
```

---

## P2-B — 启动前环境诊断

**状态：[x] 已完成**

### 目标
BAT 启动前检查以下项，发现问题立刻给出明确提示：

| 检查项 | 检查方式 | 结果 |
|--------|----------|------|
| ffmpeg 可用 | `where ffmpeg` | 阻断 |
| ffprobe 可用 | `where ffprobe` | 阻断 |
| `Videos\.stream` 可写 | 写测试文件 | 阻断 |
| 磁盘空间充足（建议 >10GB） | PowerShell `Get-PSDrive` | 警告 |
| `TRANSCRIBE_BACKEND` 当前值 | 打印环境变量 | 仅信息 |
| Playwright 浏览器 | 跳过（路径太脆弱，误报率高） | — |

### 决策
- 全部放 BAT，不加 `preflight.py`（逻辑简单，不值得额外 Python 进程）
- Playwright 检查跳过：可靠查 Chromium 路径在 BAT 里太脆弱，误报率高
- 诊断在 Cookie 预检之后、日志目录创建之前运行

---

## P2-C — 账号被踢/登录失效错误细分

**状态：[ ] 待讨论**

### 现状
失败时统一报"session expired"，无法区分根因。

### 目标细分

| 场景 | 目标日志 |
|------|----------|
| 页面跳到登录页 | `[账号态失效] 跳转登录页，请重新登录` |
| 页面正常但无媒体 URL | `[直播未开始或已结束] 页面无流 URL` |
| ffmpeg 403/401 | `[媒体 URL 授权失效] 需刷新流 URL` |
| ffmpeg timeout | `[网络中断] 流连接超时` |

### 改动范围
`zhihuTTS_stream.py` + `stream_extractors.py` — 加条件判断，不改架构

### 待讨论
- 这四种场景，现有代码里哪些已有判断，哪些需要新增？

---

## 讨论进度

| 项目 | 状态 |
|------|------|
| P0 录流解耦 | ✅ 方案已定，待实现 |
| P1-A 专用账号 | ✅ 已完成 |
| P1-B BAT 固化 | ✅ 已完成 |
| P1-C Checkpoint Resume | ✅ 已完成 |
| P2-A 主动 URL 刷新 | 🔜 推迟到 P0 Step2 |
| P2-B 启动前诊断 | ✅ 已完成 |
| P2-C 错误细分日志 | ⬜ 待讨论 |
