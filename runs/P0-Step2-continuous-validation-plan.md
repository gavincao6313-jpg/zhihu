# P0 Step 2 — --continuous-hls 直播验证计划

> 提交于 b7525fc (`--max-chunks` 修复已包含)
> 由 MAC 端起草，WIN 端执行验证

---

## 验证 1：核心链路 `--continuous-hls`

真实直播时运行，测试 Recorder + SegmentConsumer 双线程完整链路。

```bash
python -u zhihuTTS_stream.py --continuous-hls --stream-work-dir Videos\.stream --name continuous-verify
```

| # | 检查项 | 通过标准 |
|---|--------|----------|
| 1 | Recorder 正确写 .ts | `Videos\.stream\` 中出现 `seg_*_*.ts` 文件 |
| 2 | Consumer 不读 temp 文件 | 日志无 `.tmp` 或未完成文件被处理 |
| 3 | Manifest 按词法排序 | chunk 顺序 = filename 排序（非 mtime） |
| 4 | `start_s` 累积误差 < 1s | 每 chunk start_s 对比 ffprobe 推算值 |
| 5 | Recorder 停止后处理 tail | 直播结束 / Ctrl+C 后剩余 .ts 被扫完 |
| 6 | 输出完整 | manifest.json + manifest.md + combined-transcript.txt |
| 7 | 无 ERROR / Traceback | 全程无异常 |

---

## 验证 2：`--max-chunks` 修复确认

b7525fc 修复了 `--max-chunks` 在 consumer-only 被忽略的 bug。

```bash
python -u zhihuTTS_stream.py --hls-consumer-only --stream-work-dir Videos\.stream --name maxchk --max-chunks 3
```

通过标准：

- 日志显示 `Reached --max-chunks=3, stopping.`
- Manifest 恰好 3 个 chunk
- 即使目录中有 100+ .ts 也只处理 3 个
- `--max-chunks=0`（默认）仍处理全部

---

## 验证 3：旧路径回归

不加 `--continuous-hls` 的 URL 切片路径不受影响：

```bash
python -u zhihuTTS_stream.py --url <replay-url> --name regression-check --chunk-duration 60 --max-chunks 3
```

通过标准：表现与 Step 1 一致，正常生成 3 个 chunk。

---

## 结果速查表

| 验证 | 耗时 | 依赖 | 状态 |
|------|------|------|------|
| 1 — `--continuous-hls` | 直播全程 | 真实直播 | ❓ 等今晚直播 |
| 2 — `--max-chunks` 修复 | ~2 min | 已有 .ts 文件 | ✅ b7525fc |
| 3 — 旧路径回归 | ~5 min | 任意回放 URL | ✅ 7686e30 |

---

## V2 结果 (2026-05-22)
- `--max-chunks=3` → `Reached --max-chunks=3, stopping.` → 恰好 3 chunk
- Manifest: `stream-step2-fix2-20260522-002531.manifest.md`
- 修复提交: `b7525fc`

## V3 结果 (2026-05-22)
- `--url <vdn3.vzuu.com>` → 3 chunk, extractor=direct, mode=fixed duration
- 0 re-extracts, 3/3 slices kept, 与 Step 1 表现一致
- Manifest: `stream-regression-check-20260522-003925.manifest.md`

---

## 完成条件

三项全部 ✅ 通过 → **P0 Step 2 完成**，可进入 P0 Step 3/4 或 P1 计划阶段。
