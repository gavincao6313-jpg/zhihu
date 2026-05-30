# WIN 验证交接：Qwen 滑动窗口 overlap 修复验证

**日期：** 2026-05-30  
**负责人：** WIN 执行  
**目标：** 验证 `build_qwen_windows` overlap 修复后，下场直播 Qwen Plus + 128f 产生 8 个窗口（修复前为 6 个）

---

## 背景

上场直播（2026-05-29，696 帧）Qwen Plus + 128f 滑动窗口产生了 6 个窗口、无 overlap，
导致第 5 章横跨 47 分钟、章节颗粒度过粗。

根因：`target_new_frames = min(200, 128) = 128`，`overlap = (128-128)//2 = 0`。

修复后（已推送至 main）：
- 自动检测 overlap 归零的情况，还原 `target=88, overlap=20`
- 696 帧 → **8 个窗口**，每窗 ~19 分钟，与 Gemini 8 章节对齐

---

## Step 0：拉取最新代码

```bat
cd d:\zhihu\zhihu_file
git pull origin main
```

---

## Step 1：下场直播启动命令

与上场一致，使用 Qwen Plus + 128f：

```bat
set DASHSCOPE_API_KEY=your_key
set QWEN_MODEL=qwen3.6-plus
run_zhihu_live.bat "<直播间URL>" --provider qwen --qwen-max-frames 128
```

---

## Step 2：验证窗口数（合成完成后）

合成完成后，在 `runs/` 目录找到 `stream-<NAME>-<时间>.final-qc.json`，确认：

```json
{
  "synthesis_pass": "sliding-window",
  "qwen_window_policy": {
    "window_count": 8,
    "overlap_frames": 160
  }
}
```

同时确认 log 里出现：
```
[auto-route] transcript XXXXX chars > 30000: Qwen one-shot → sliding-window
```

---

## 验收标准

| 指标 | 修复前（2026-05-29） | 验收目标 |
|------|---------------------|---------|
| 窗口数 | 6 | **8** |
| 每窗口 overlap | 0 帧 | **20 帧** |
| 最大单章时长 | 47 分钟 | ≤ 25 分钟 |
| 尾部 gap | 59s | ≤ 60s |
| 正文字符 | 176,431 | ≥ 176,000（维持或提升） |

---

## 如果合成失败（Step 3 报错）

续跑命令（复用已完成窗口笔记，不重新消耗配额）：

```bat
set DASHSCOPE_API_KEY=your_key
set QWEN_MODEL=qwen3.6-plus
python scripts\build_stream_markdown.py ^
  --base <NAME> ^
  --provider qwen ^
  --synthesis-pass sliding-window ^
  --resume-window-notes ^
  --qwen-max-frames 128 ^
  --output-label qwen-plus-sw-8w
```

---

## 推送验证结果

```bat
git add runs\ Markdowns\
git commit -m "verify(win): Qwen Plus sw-128f-8w — <窗口数>w, <正文字符>chars, gap <Xs>"
git push origin main
```
