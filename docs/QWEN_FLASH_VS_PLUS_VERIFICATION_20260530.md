# Qwen Flash vs Plus — 回放视频滑动窗口对比验证

**日期：** 2026-05-30 | **执行：** WIN | **目标：** 长视频场景下 Qwen3.6-flash vs qwen3.6-plus 质量对比

---

## 测试条件

```
视频: replay-verify-20260530 (vzuu.com, 268MB, 160min)
转写: 52,934 字 | 帧数: 541 | chunks: 159
策略: 滑动窗口 (auto-route, >30K触发) | 帧上限: 128/窗
文件: convert_payload_to_chunks.py + build_stream_markdown.py
```

## 结果对比

### 整体

| 指标 | qwen3.6-flash | qwen3.6-plus | 差异 |
|------|:--:|:--:|:--|
| 窗口数 | 7 | 7 | 同 |
| overlap | 233 | 233 | 同 |
| 覆盖 | gap 50s | gap 50s | 同 |
| 总字符 | 149,829 | **161,345** | +7.7% |
| final assembly | 13,218 | **19,684** | **+49%** |

### 每窗口输出

| 窗口 | flash | plus | 评价 |
|------|------:|------:|------|
| W1 | 115,329 ⚠️ | 9,247 | flash 疑似失控 |
| W2 | 4,615 | 7,642 | plus 更充实 |
| W3 | 49,173 ⚠️ | 8,682 | flash 疑似失控 |
| W4 | 5,468 | 8,344 | plus 更充实 |
| W5 | 5,622 | 10,306 | plus +83% |
| W6 | 58,593 ⚠️ | 8,503 | flash 疑似失控 |
| W7 | 5,195 | 13,102 | plus +152% |
| assembly | 13,218 | 19,684 | plus +49% |

### 输出稳定性

```
flash: [4K, 5K, 5K, 5K, 49K, 58K, 115K]  → 方差极大
plus:  [7K, 8K, 8K, 8K, 9K, 10K, 13K]     → 稳定均匀
```

## 结论

1. **Plus 全面优于 Flash**：总量 +7.7%，拼装 +49%，稳定性碾压
2. **Flash 在滑动窗口下有失控倾向**：7 窗中 3 窗产出异常大（49K/58K/115K），疑似复述原文而非总结
3. **Plus 输出均匀稳定**：每窗 7-13K，方差小
4. **与直播验证结果一致**：昨晚直播 Plus+SW+128f 同样优于 Flash

## 建议

1. **`run_replay_qwen.bat` 默认模型改为 `qwen3.6-plus`**
2. **`build_stream_markdown.py` 的 `QWEN_MODEL` 默认值从 `qwen3.6-flash` 改为 `qwen3.6-plus`**
3. **`run_zhihu_live.bat` 的 Qwen 路径默认模型同步改为 plus**
4. BAT 脚本的 `pause` 命令在 `start /B` 后台模式下会卡住，建议改为仅在前台运行时 pause
