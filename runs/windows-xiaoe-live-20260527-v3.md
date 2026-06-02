# WIN → MAC: QWEN v3 验证报告 (resume-window-notes)

## 执行指令

```bash
git pull origin main
python scripts\build_stream_markdown.py \
  --base live-xiaoe-20260527 \
  --provider qwen \
  --synthesis-pass sliding-window \
  --resume-window-notes \
  --output-label qwen-v3
```

- 3 个窗口笔记复用成功（无额外 API 消耗）
- 仅 final assembly 1 次调用（2 parts），finish_reason=stop

## v2 → v3 对比

| 指标 | v2 | v3 | delta |
|------|----|----|-------|
| API 调用 | 4 (3窗+1组装) | 1 (仅组装) | -3 |
| 输出 chars | 113,724 | 194,871 | +71% |
| body_chars | 24,560 | 105,707 | +330% |
| body/transcript 比 | 0.60 | 2.57 | +328% |
| Narrative 保留率 | 15.38% (2/13) | 100% (13/13) | 已修复 |
| Narrative appendix | appended=true, 11 blocks | appended=false, 0 blocks | 已修复 |
| appendix reason | missing_or_low_retention | already_retained | 已修复 |
| missing_blocks | 11 个 | 0 个 | 已修复 |
| Critical Facts 保留 | 8/8 (100%) | 8/8 (100%) | 不变 |
| body tail gap | 12s | 12s | 不变 (同窗口) |

## 核心发现

### 1. Narrative Block 保留率已修复 (P0)
v2 pre-append 仅 2/13 blocks 被 final assembly 保留，其余 11 靠附录强制追加。
v3 的 qwen_narrative_appendix 显示 appended=false, reason="already_retained"，13/13 全部在 body 中。
qwen_narrative_retention_qc 确认 retained_block_count=13, retention_ratio=1.0, missing_blocks=[]。

### 2. 叙事证据已嵌入章节正文
章节中出现了 **叙事证据摘录：** 段落 + blockquote 引用，直接包含窗口笔记的原文。
相比 v2 所有叙事块只能堆在独立附录中，现在它们被注入到对应时间段的章节内。

### 3. body 内容量暴增 330%
body_chars 从 24,560 → 105,707，因为叙事证据被写入了章节正文而不是附录。
body/transcript 比从 0.60 涨到 2.57，说明 body 包含大量合成内容（叙事块+分析）。

### 4. 字段命名与预期有偏差
| 预期字段 | 实际字段 |
|----------|----------|
| injected_into_chapters | (无此字段) |
| appended_to_appendix | appended_blocks (布尔语义相反) |
| #### 叙事证据 小节 | **叙事证据摘录：** 加粗段落 |

功能正确，但 QC 字段名和章节标题格式与 WIN 侧预期不完全一致。

## 产物清单

| 文件 | 说明 |
|------|------|
| Markdowns/TTS_stream-live-xiaoe-20260527-qwen-v3.md | v3 最终输出 (194,871 chars) |
| runs/stream-live-xiaoe-20260527-20260527-222309.qwen-v3.final-qc.json | v3 QC 清单 |
| runs/windows-xiaoe-live-20260527-v3.md | 本验证报告 |
