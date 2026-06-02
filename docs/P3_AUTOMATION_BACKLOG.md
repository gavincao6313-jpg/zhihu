# P3 自动化积压 — 待完成（非阻塞）

> 记录时间：2026-06-02
> P1/P2 已完成，P3 不阻塞日常运营，但影响体验和质量上限。

---

## P3-A：Qwen 双 Provider 并行合成

**现状**：`launch_live_pipeline` 和 `launch_replay_pipeline` 只运行单 provider（由前端 plan 选定，默认 Gemini）。

**目标**：同一次直播/回放，在 Gemini 合成完成后紧接着跑一次 Qwen（或并行），产出两份 Markdown 供对比。

**方案草稿**：
- `launch_live_pipeline` 在 Step 3 synthesis 完成后，再以 provider=qwen 运行一次 `build_stream_markdown.py`
- 或在 `build_run_plan()` 增加 `dual_provider: bool` 字段，server 端串行执行两次 synthesis
- 配额约束：每次直播消耗 2 次 Gemini 调用（1 Gemini + 1 Qwen），需确认在 Free tier 100 RPD 内

**验收标准**：`/api/runs` 返回同 base 两条记录，前端分别显示 gemini/qwen 标签。

---

## P3-B：启动前 Auth 存活检测

**现状**：`zhihu_auth_state.json` 过期时，Playwright 在流开始几分钟后才失败，已跑的 chunks 浪费了时间。

**目标**：`launch_live_pipeline` 启动前快速验证 auth 是否仍然有效。

**方案草稿**：
- 在 `launch_live_pipeline` 中，抓取 `zhihu.com` 首页并检查是否跳登录页（HTTP 302 / 包含"登录"字样）
- 或在前端"启动"前调用 `/api/check-auth` 接口，server 端快速探针
- 失败时立即报错"登录已过期，请重新运行 python login_save_auth.py"

**验收标准**：auth 过期时，点击"启动"后 5s 内前端显示明确的登录失效提示，不等待 pipeline 超时。

---

## P3-C：前端后台轮询保活

**现状**：浏览器标签页隐藏（background）超过约 60s 后，`setInterval` 被浏览器节流，前端 3s 轮询可能变成 1-2min 一次，导致 Logs/Chunks 更新滞后。

**目标**：在标签页不活跃时保持基本轮询频率，或通过 WebSocket/SSE 推送替代轮询。

**方案草稿**：
- Web Worker 内的 `setInterval` — Worker 不受页面 visibility 限制，几行代码
- 或改 `/api/runs/{id}` 轮询为 SSE（Server-Sent Events），server 端推送状态变更

**推荐方案**：Web Worker 轮询最简单，无需改 server。

**验收标准**：直播 90 分钟中，标签页隐藏期间前端 Chunks 计数最多滞后 30s。

---

## P3-D：--continuous-hls 合并评估

**现状**：main 分支用 `run_validation()` URL-slice 顺序切片（2026-06-02 验证通过：87 chunks / 187KB）。
`feature/stream-transcript-validation` 有 Recorder/Consumer 并发录制架构（`--continuous-hls`），无切片间隙但代码复杂度更高。

**决策背景**：2026-06-02 直播用 `run_validation()` 成功，短期内保留当前路径。

**评估触发条件**（以下任一发生时重新评估）：
- `run_validation()` 出现明显的切片间隙导致内容丢失
- 下次直播超过 2 小时且有网络抖动
- WIN 用户报告 HLS 模式在同等条件下更稳定

**保留分支**：`feature/stream-transcript-validation` 不删除，作为备用路径。

---

*下次直播前 Review：P3-B（auth 检测）影响可靠性最高，建议优先。*
