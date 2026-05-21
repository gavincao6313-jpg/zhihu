# 直播流优化讨论计划

> 记录于 2026-05-21。逐条讨论，讨论完一项在 [ ] 打勾。

---

## P0 — 录流与转写彻底解耦

**状态：[ ] 待讨论**

### 现状问题
当前流程是串行的：抓 60s 片段 → 本地转写/抽帧 → 再抓下一段。
转写/抽帧耗时约 20s 时，这 20s 内没有录流，真实直播会漏内容。

### 目标结构
- Thread-A（录制）：ffmpeg 持续录制并分段写入 60s 文件
- Thread-B（处理）：监听新文件，异步做 SenseVoice + 抽帧 + 合并

### 关键技术细节（已讨论）
- 用 `-segment_list segments.csv -segment_list_flags +live` 而不是轮询文件大小
  — ffmpeg 每写完一个分段才 append 到 CSV，Consumer tail 这个 CSV 拿完整文件名
- Thread-A 维持现有 Playwright keepalive + URL 刷新逻辑不动
- 两线程间用 `queue.Queue` 传文件名，Thread-B 失败不中断 Thread-A
- 改动集中在 `zhihuTTS_stream.py` 的 `run_validation()` + 新增 `consume_segment()` 线程
- BAT 层不需要变

### 待讨论
- Thread-B 崩溃时是否要 restart，还是仅记错误继续？
- 同一时刻 Thread-B 还在处理上一个 chunk 时，如果又来了新 chunk，是排队还是丢弃？
- checkpoint 文件格式是否需要随架构变化调整？

---

## P1-A — 专用账号（运营规范）

**状态：[ ] 待讨论**

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

**状态：[ ] 待讨论**

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

**状态：[ ] 待讨论**

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

**状态：[ ] 待讨论**

### 现状
CC FLV URL 的 `auth_key` 有有效期（约 8h）。当前策略：URL 失败后刷新。

### 目标
- 记录每次捕获 URL 的时间戳
- 每隔 30-60 分钟主动刷新一次 Playwright 页面拿新 URL
- 刷新失败不立刻停，继续用旧 URL，直到旧 URL 失败才报错

### 改动范围
`stream_extractors.py` — 加计时器和主动刷新逻辑

### 待讨论
- 刷新间隔设多少合适（`auth_key` 实际 TTL 是多少，8h 还是更短）？
- 主动刷新期间 Thread-A 是否暂停录制，还是切 URL 时做无缝衔接？

---

## P2-B — 启动前环境诊断

**状态：[ ] 待讨论**

### 目标
BAT 启动前检查以下项，发现问题立刻给出明确提示：

| 检查项 | 检查方式 |
|--------|----------|
| ffmpeg / ffprobe 可用 | `where ffmpeg` |
| Playwright 浏览器已安装 | 检查对应 `.exe` 路径 |
| `zhihu_auth_state.json` 含 `z_c0` | `check_auth.py` 扩展 或 Python 一行 |
| `Videos\.stream` 可写 | 写测试文件 |
| 磁盘空间充足（建议 >10GB） | PowerShell `Get-PSDrive` |
| `TRANSCRIBE_BACKEND` 当前值 | 打印环境变量 |
| Gemini 是否启用，预计是否触发 API 调用 | 打印 `GEMINI_API_KEY` 状态 |

### 待讨论
- 诊断逻辑放在 BAT 里还是单独 `preflight.py`？
- 哪些项是阻断性的（检查失败直接退出），哪些是警告？

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
| P0 录流解耦 | ⬜ 待讨论 |
| P1-A 专用账号 | ⬜ 待讨论 |
| P1-B BAT 固化 | ⬜ 待讨论 |
| P1-C Checkpoint Resume | ⬜ 待讨论 |
| P2-A 主动 URL 刷新 | ⬜ 待讨论 |
| P2-B 启动前诊断 | ⬜ 待讨论 |
| P2-C 错误细分日志 | ⬜ 待讨论 |
