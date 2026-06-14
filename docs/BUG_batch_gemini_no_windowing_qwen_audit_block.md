# BUG: Gemini 缺少滑动窗口 + Qwen 审核阻断 → 大视频双重死锁

**报告日期**: 2026-06-14  
**报告人**: Windows Runner (gavincao6313-jpg)  
**目标文件**: `zhihu_file/batch_process_external.py`  
**严重程度**: 🔴 高 — 导致 3/28（就业速成班）视频永久无法完成

---

## 问题描述

对于时长 >2.5h 的大视频（1000+ 关键帧 + 4-5万字符逐字稿），存在双重死锁：

1. **Gemini 路径**: 输入 token 超过 1,048,576 限制 → `400 INVALID_ARGUMENT`，无法处理
2. **Qwen 路径**: 部分窗口帧被审核拦截 → `data_inspection_failed` → 单个窗口失败 → 整组合成失败

两个模型各自能处理一部分，但都无法独立完成。目前没有跨模型的降级恢复机制。

---

## 复现证据

### 案例 1: 007_Cursor编程-从入门到精通（3h10m）

```
Provider: gemini (路由)
输入: 2186 parts (1 prompt + 1 transcript + 1092 frames × 2)
错误: 400 INVALID_ARGUMENT — "The input token count exceeds the maximum number of tokens allowed 1048576."
```

Gemini 无窗口化策略，全量发送 1092 帧，超过 1M token 限制。

### 案例 2: 024_项目实战：企业知识库下（3h25m）

```
Provider: qwen (路由)
分窗: 6 windows, W1-W5 成功, W6 (116 frames) 失败
错误: 400 InternalError.Algo.DataInspectionFailed — "Input image data may contain inappropriate content."
结果: W6 失败 → 无法 Assembly → 整组合成失败
```

5/6 窗口成功产出内容（~35K chars），仅因最后1个窗口被审核拒绝，前功尽弃。

### 案例 3: 028_项目实战：智能招聘面试模拟系统下（3h20m）

```
Provider: qwen (路由)
分窗: 6 windows, W1 (231 frames) 失败, W2-W6 成功
错误: 400 InternalError.Algo.DataInspectionFailed — "Input image data may contain inappropriate content."
结果: W1 失败 → 无法 Assembly → 整组合成失败
```

5/6 窗口成功产出内容（~43K chars），仅因第1个窗口被审核拒绝，前功尽弃。

### API 调用浪费统计

| 视频 | Gemini 调用 | Qwen 调用 | 浪费 |
|------|:----------:|:---------:|:----:|
| 007 | 3 (Token超限) | — | 3 Gemini |
| 024 | 6 (早期尝试) | 6 | 12 总调用 |
| 028 | 6 (早期尝试) | 6 | 12 总调用 |

---

## 根因分析

### 根因 1: Gemini 无窗口/采样策略

`batch_process_external.py` 中：
- Qwen 有 `QWEN_MAX_FRAMES = 250` 和自动分窗逻辑（`_synthesize_qwen_windowed`）
- Gemini **没有**等效的帧数上限或分窗逻辑 — 全量发送所有关键帧

```python
# 当前 Gemini 路径（无窗口限制）
# 直接发送所有 frames → 超 1M token 限制
result = _synthesize_gemini(client, vpath, output_path, ...)
```

### 根因 2: Qwen 审核阻断无降级

Qwen 分窗合成中，任一窗口被审核拒绝（`data_inspection_failed`），整个视频即标记失败。失败的窗口内容无法由 Gemini 补充（因为 Gemini 无法处理完整视频）。

关键代码在 `_synthesize_qwen_windowed()` 中（大致逻辑）:
```python
for window in windows:
    result = call_qwen(window_frames)
    if result.error == 'data_inspection_failed':
        # 直接跳过 → 后续 Assembly 无法进行 → 整体失败
        continue
```

### 根因 3: 无跨模型降级路径

两个模型各有一个"盲区"：
- Gemini 盲区: >1M token 输入（无窗口）
- Qwen 盲区: 某些帧触发内容审核

目前没有机制让失败的窗口/分段在另一个模型上重试。

---

## 建议修复方案（Mac 侧）

### 方案 A: Gemini 加窗口化（推荐，与 Qwen 对称）

1. 在 `batch_process_external.py` 中为 Gemini 添加 `GEMINI_MAX_FRAMES`（建议 128-200）
2. 实现 `_synthesize_gemini_windowed()` — 参考现有 `_synthesize_qwen_windowed()` 的分窗 + Assembly 策略
3. Gemini 的 1M token 限制对应约 200-250 frames（按当前 frame 编码大小估算）

### 方案 B: Qwen 审核失败 → Gemini 窗口降级

1. Qwen 窗口失败时，不直接放弃；将失败的窗口 frames 发送到 Gemini（单窗口 frames 少，不超 token 限制）
2. 混合模型的 Assembly 需同时处理 Qwen 和 Gemini 产出的窗口笔记

### 方案 C: Qwen 审核帧自动重采样

1. 当 Qwen 返回 `data_inspection_failed` 时，将该窗口的 frames 进一步采样（如取一半），重新发送
2. 可降低触发审核的帧被选中的概率

### 方案 D: 组合方案（最稳健）

A + B：Gemini 有窗口化能力，Qwen 审核失败的窗口用 Gemini 补位。

---

## 影响范围

- **就业速成班**: 3/28 视频阻塞（007, 024, 028）
- **潜在影响**: 所有时长 >2.5h 且包含"敏感"截图（如简历、招聘页面、企业数据）的视频
- **新编程班**: 12 个 Qwen 路由的视频（其中可能包含类似内容）
- **OpenClaw**: 全 Gemini 路由（73个），如添加窗口化可能加快处理

---

## Windows 侧已验证的临时规避

无可用规避。已尝试：
1. 手动改 provider 为 qwen → 审核阻断
2. 手动改 provider 为 gemini → Token 超限
3. 两个模型各自只能完成部分工作，但无法独立完成
