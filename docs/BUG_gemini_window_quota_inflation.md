# BUG: Gemini 分窗阈值过低 + 配额计数膨胀

**报告日期**: 2026-06-16  
**报告人**: Windows Runner (gavincao6313-jpg)  
**目标文件**: `zhihu_file/batch_process_external.py`  
**严重程度**: 🟡 中 — 导致日处理量从理论 20 个降至实际 3-4 个，拖慢整体进度

---

## 问题 A: 分窗阈值过于保守

### 现状
`GEMINI_MAX_FRAMES = 200` (第69行)。大部分短视频（1-2h）产生 300-600 关键帧，全部触发分窗。

### 复现数据 (2026-06-15~16 三轮 batch 运行)

| 视频 | 帧数 | 分窗 | 实际 API 调用 |
|------|:--:|:--:|:--:|
| 013_音频处理模型实战技巧 | 114 | 无 | 2 (1+1续写) |
| 024_交付过程中的问题解析 | 538 | 3窗 | 4 (3窗+Assembly) |
| 026_游戏化识字与记单词 | 334 | 2窗 | 3 (2窗+Assembly) |

### 根因
200 帧约 100K tokens，远低于 Gemini 1M 上限。实际安全值：

```
600 帧 × 500 token/帧 + 50K 逐字稿 + 2K prompt ≈ 350K token
```

建议 `GEMINI_MAX_FRAMES = 600`，大部分课程3/4视频可直接单次调用完成。

### 对比

| 视频 | 修复前 | 修复后 |
|------|:--:|:--:|
| 300帧视频 | 2窗+Assembly = 3次 | **1次** |
| 500帧视频 | 3窗+Assembly = 4次 | **1次** |
| 1000+帧视频 | 仍需分窗 | 仍需分窗 ✅ |

1000+ 帧大视频（>3h 长课）的分窗保护仍然生效。

---

## 问题 B: 分窗配额计数器膨胀

### 现象
实际 API 调用 4 次，配额计数器记录 12 次（3x 膨胀）。

### 复现
- 视频 024：实际 4 次调用 (W1/W2/W3/Assembly)，计数器 +12
- 视频 026：实际 3 次调用 (W1/W2/Assembly)，计数器 +9

### 影响
每天 20 配额，实际只能完成 3-4 个视频（而非理论 15-20 个）。

### 疑似位置
`_process_gemini_windowed()` 函数中每次窗口调用和 assembly 调用的计数逻辑可能存在倍数放大。

---

## 修复建议

1. **改第 69 行**: `GEMINI_MAX_FRAMES = 200` → `600`
2. **审计配额计数**: 检查 `_process_gemini_windowed()` 中 `api_calls` 累加逻辑

两者独立，建议一起修。

---

## 已执行的验证

```
Windows 三轮批量运行实测:
- GEMINI_MAX_FRAMES=200 → 3-4 视频/天
- 实际 API 调用仅 9-12 次/天，远低于 20 配额
```

---

## 相关文件

- `docs/BUG_batch_gemini_no_windowing_qwen_audit_block.md` — 关联: Mac 之前添加了 Gemini 分窗，但阈值偏保守
- `batch_process_external.py` — 第 69 行 `GEMINI_MAX_FRAMES`、第 459 行 `_process_gemini_windowed()`

**Why:** 当前阈值导致每日处理效率降低 5-7x，严重拖慢 F:\AI研发 178 个 MP4 的整体进度。
