# WIN → MAC Handoff: 小鹅通直播 2026-05-27 双模型对比

## 直播概况

- **平台**: 小鹅通 (xet.pomoho.com)
- **起止时间**: 19:59 → 22:23 CST (约 143 分钟)
- **HLS CDN**: `liveplay.xiaoe-live.com` / `liveplay-byte.xiaoeknow.com`
- **模式**: Playwright keepalive + continuous HLS + SenseVoice 60s chunked
- **TS 片段**: 144 段 (seg_000000–seg_000143)
- **Chunk 数量**: 144 (0s–8636s, 无 gap)

## 双模型产物

| 文件 | 说明 |
|------|------|
| `Markdowns/TTS_stream-live-xiaoe-20260527-qwen-v2.md` | QWEN v2 最终输出 (113,724 chars) |
| `Markdowns/TTS_stream-live-xiaoe-20260527-gemini35.md` | Gemini 3.5 Flash 最终输出 (96,527 chars) |
| `runs/stream-live-xiaoe-20260527-20260527-222309.qwen-v2.final-qc.json` | QWEN QC (54KB, 全部通过) |
| `runs/stream-live-xiaoe-20260527-20260527-222309.gemini35.final-qc.json` | Gemini QC (1.4KB, 全部通过) |
| `runs/stream-live-xiaoe-20260527-20260527-222309.qwen-window-00*.notes.md` | QWEN 3 个窗口笔记 |
| `runs/stream-live-xiaoe-20260527-20260527-222324.manifest.md` | 完整时序清单 (145KB) |
| `runs/stream-live-xiaoe-20260527-20260527-222324.manifest.json` | 完整时序清单 JSON (734KB) |
| `runs/stream-live-xiaoe-20260527-20260527-222324.combined-transcript.txt` | 合并转录 (116KB, 41,147 chars) |

## 实时录制流水线验证

**pipeline 自动检测到了直播结束并触发 merge。** Recorder + Consumer 双线程运行正常：

- 60s chunk 转录延迟: 9-16s/chunk（稳定）
- Keyframe 提取: 351 帧（203 被 annotation 选中，0 张 slide）
- Consumer 实时产出 chunk JSON/transcript/md，间隔稳定 ~60s
- Stream 结束后自动生成 combined-transcript + manifest

## 核心对比发现

### 1. QWEN Narrative Block 保留率严重不足（已知问题复现）

- **pre-append 阶段**: 13 个 window notes 中仅 2/13 (15.38%) 被 final assembly 保留到 body
- **剩余 11 个 blocks** 靠 `qwen_narrative_appendix` 附录机制强制补回
- **和 replay 测试表现一致** — 这是 QWEN `qwen-final-assembly-v2` 的系统性问题，不是单次偶发
- **根因推测**: final assembly prompt 在整合 3 个窗口笔记时的压缩/摘要倾向过强，导致细粒度叙事块被丢弃

### 2. QWEN body 尾部 gap 比 Gemini 大

- Gemini: last chapter 02:23:55, stream end 02:23:56, **gap 1s**
- QWEN: last chapter 02:23:44, stream end 02:23:56, **gap 12s**
- 直播结尾通常是 Q&A 或总结，gap 12s 可能丢失收尾内容

### 3. Gemini 一次调用覆盖 351 帧 无压力

- 704 parts, 1 次 API call, 7,364 chars synthesis
- cap 3000 但实际只用 351 帧 — 远未触顶
- body 覆盖完美 (1s gap)
- 输出 96,527 chars — 结构简练但信息密度高

### 4. QWEN 321 窗口策略运行正常（结构层面）

- 3 个窗口覆盖 0s–8624s，时间上无重叠无遗漏
- 每窗口 128 frames cap，帧分配合理 (128/128/95)
- Fact Retention: 8/8 (100%)
- Critical Facts: 8 条 (date_or_age × 6, percentage × 2) — 偏少
- Window finish_reason: 全部 stop（无截断）
- Timeline QC: 0 个 overlap，chapters 正确分布
- 总 token 102,330 (81.5K in / 20.7K out), 4 次 API 调用

### 5. Gemini lack QWEN's structured appendices

Gemini 没有:
- Critical Facts Index
- Narrative Evidence Blocks
- Technical Assets appendix

但 Gemini 的 body 文风更连贯流畅，信息密度更高。

## P0/P1 状态回顾

| 级别 | 问题 | 状态 |
|------|------|------|
| P0 | BAT 双平台 (zhihu/xiaoe) 支持 | done (origin/main 已有) |
| P0 | Auth routing (zhihu/z_c0 vs xiaoe/ko_token) | done (origin/main 已有) |
| P1 | is_live() HLS 检测 | 未修，但 continuous-hls 路径不经过 `slice_url()`，不影响直播 |
| P1 | MEDIA_PATTERNS 缺少 xiaoe CDN | 不影响匹配 |
| P1 | _on_response CC API 解析 | 死代码，无害 |

## MAC 侧建议分析项

1. **QWEN final-assembly-v2 的 Narrative Block 保留问题** — 最高优先级。15% 保留率意味着窗口笔记的大部分结构化内容被丢弃，附录机制是 workaround 而非修复
2. **QWEN body tail gap 12s 排查** — 对比 final assembly 输入是否收到了 window-003 的最后 12s 内容
3. **Gemini one-shot 是否可以直接替代 QWEN sliding-window** — 1 次调用 vs 4 次调用，输出质量相当，且无 retention 问题
4. **Critical Facts 提取数量偏少** (8 条 vs 之前 replay 的 32 条) — 因为 3 个窗口 vs 之前 replay 的 8+ 个窗口导致？还是直播内容密度较低？
