# WIN 今日头条 missing_payload 交接记录 2026-05-29

## 目标

继续处理当前今日头条收藏夹里的 `18 missing_payload` 视频。不考虑从手机 App 导出，继续走 Web 端自动化。

## MAC 端已完成

1. 已确认历史短视频 pipeline 不需要重做：
   - 当前历史 payload/Markdown 已对齐到 `67/67`。
   - 原唯一 `payload_only` 已用 deterministic fallback 生成 Markdown 并通过 `split-pack` QC。
2. 已新增收藏夹分类、source-card、reconcile、missing 队列脚本：
   - `scripts/toutiao_classify_favorites.py`
   - `scripts/toutiao_build_source_cards.py`
   - `scripts/toutiao_reconcile_favorites.py`
   - `scripts/toutiao_export_missing_payload_queue.py`
   - `scripts/toutiao_update_source_cards_from_reconcile.py`
   - `scripts/toutiao_probe_media_candidates.py`
3. 已修正下载器：
   - `scripts/toutiao_download_favorites.py --content-type`
   - `scripts/toutiao_download_favorites.py --queue-json`
   - `scripts/toutiao_download_favorites.py --item-id`
   - `scripts/toutiao_download_favorites.py --playwright-mobile`
4. MAC 端实测突破点：
   - 桌面 `yt-dlp` 路径仍失败：`Failed to get SSR_HYDRATED_DATA`。
   - 移动 `m.toutiao.com/video/<id>/` 页面会触发 `vod.bytedanceapi.com GetPlayInfo`。
   - 浏览器随后访问 `v*.toutiaovod.com/...&mime_type=video_mp4...`，HTTP `206 video/mp4`。
   - `toutiao-7642741463595385385` 已在 MAC 下载成功，文件为 23.90s MP4；视频目录被 `.gitignore` 忽略，不会随 Git 推送。
5. MAC 端阻塞：
   - `short_video_pipeline.py preprocess` 在本机 ASR 阶段失败：
     - 默认：`FUNASR/SenseVoice 未安装。请先安装 funasr、modelscope、torch、torchaudio。`
     - `TRANSCRIBE_BACKEND=auto`：`No module named 'faster_whisper'`
   - 由于会话余额告急，`pip install --user faster-whisper` 已被中断，不继续在 MAC 安装依赖。

## WIN 执行环境预检

```bat
git pull
python -m pip install -r requirements.txt
python -m playwright install chromium
ffmpeg -version
ffprobe -version
```

如果 WIN 已有 SenseVoice/FunASR 环境，可以继续使用默认 ASR。否则先用：

```bat
set TRANSCRIBE_BACKEND=auto
```

## WIN 重新生成当前收藏夹队列

`cache/` 不进 Git，所以 WIN 需要重新登录并生成本机 manifest/reconcile/queue。

```bat
python scripts\toutiao_login.py --login-url "https://www.toutiao.com/"
```

登录后：

```bat
python scripts\toutiao_classify_favorites.py --max-pages 20 --scrolls 0 --screenshot --update-manifest --headed
```

记录输出的 classify JSON 路径，例如：

```text
cache/toutiao/probes/classify-YYYYMMDDTHHMMSS.json
```

生成 reconcile：

```bat
python scripts\toutiao_reconcile_favorites.py --label win-current
```

生成 missing 队列，把 `classify-...json` 替换成上一步实际路径：

```bat
python scripts\toutiao_export_missing_payload_queue.py ^
  --reconcile-json cache/toutiao/probes/reconcile-win-current.json ^
  --classify-json cache/toutiao/probes/classify-YYYYMMDDTHHMMSS.json ^
  --label win-missing18
```

检查队列：

```bat
python scripts\toutiao_download_favorites.py ^
  --queue-json cache/toutiao/probes/missing-payload-queue-win-missing18.json ^
  --new-only ^
  --dry-run
```

预期：只选中 `missing_payload` 队列项，不应扫到 57 条或历史已完成视频。

## 先复核 MAC 成功样本

先跑 23 秒样本，确认 WIN 端也能捕获移动 Web mp4：

```bat
python scripts\toutiao_download_favorites.py ^
  --queue-json cache/toutiao/probes/missing-payload-queue-win-missing18.json ^
  --item-id toutiao-7642741463595385385 ^
  --prefer-playwright ^
  --playwright-mobile ^
  --headed ^
  --timeout-ms 30000
```

成功标志：

```text
ok: ...Videos/short/toutiao/toutiao-7642741463595385385.mp4 [mobile-playwright-capture]
```

验证：

```bat
ffprobe -v error -show_entries format=duration,size -show_streams -of json Videos\short\toutiao\toutiao-7642741463595385385.mp4
```

MAC 参考值：

```text
duration: 23.900000
video: h264, 480x360, 30 fps
audio: aac, 48000 Hz, stereo
size: about 1009654 bytes
```

## 批量下载 18 条 missing_payload

样本通过后再批量：

```bat
python scripts\toutiao_download_favorites.py ^
  --queue-json cache/toutiao/probes/missing-payload-queue-win-missing18.json ^
  --new-only ^
  --prefer-playwright ^
  --playwright-mobile ^
  --headed ^
  --timeout-ms 30000
```

如果担心批量失败，先限制 3 条：

```bat
python scripts\toutiao_download_favorites.py ^
  --queue-json cache/toutiao/probes/missing-payload-queue-win-missing18.json ^
  --new-only ^
  --limit 3 ^
  --prefer-playwright ^
  --playwright-mobile ^
  --headed ^
  --timeout-ms 30000
```

## 下载失败时的取证命令

对失败 item 运行媒体候选探针：

```bat
python scripts\toutiao_probe_media_candidates.py ^
  --queue-json cache/toutiao/probes/missing-payload-queue-win-missing18.json ^
  --item-id <toutiao-item-id> ^
  --limit 0 ^
  --variants original,toutiao-group,ixigua-mobile,ixigua-www ^
  --headed ^
  --mobile ^
  --save-html ^
  --label win-probe-<toutiao-item-id>
```

重点看输出 JSON/MD：

- 是否出现 `vod.bytedanceapi.com/?Action=GetPlayInfo`
- 是否出现 `206 video/mp4`
- 是否只有 `打开App看完整内容` / `下载西瓜视频`

如果有 `video/mp4` 但下载器没捕获，检查 URL 是否不含 `.mp4`，而是 `mime_type=video_mp4` 或 `toutiaovod.com`。当前下载器已经覆盖这两种特征。

## 进入短视频 pipeline

下载成功后：

```bat
python scripts\short_video_pipeline.py preprocess --videos-dir Videos\short\toutiao
python scripts\short_video_pipeline.py synthesize --dry-run --write-plan
```

如果 preprocess 报 ASR 缺依赖：

```bat
python -m pip install -r requirements.txt
set TRANSCRIBE_BACKEND=auto
python scripts\short_video_pipeline.py preprocess --videos-dir Videos\short\toutiao
```

如果 WIN 有 SenseVoice 环境，不要强制改 backend，默认即可。

## 停止条件

立刻停止并回传日志，不要硬刷：

1. 连续 3 个队列 item 都没有捕获 `video/mp4`。
2. 出现验证码、登录态失效、访问过快提示。
3. `mobile-playwright-capture` 成功下载但 ffprobe 无法读取。
4. preprocess 已生成 payload，但 Qwen 合成/拆包失败。

## 回传材料

WIN 完成后提交并推送：

- `cache/toutiao/probes/*.md` 中关键报告可复制到 docs，cache 本身不进 Git。
- `runs/short-video/preprocess/*.payload.json`
- `runs/short-video/short-video-progress.json`
- `Markdowns/TTS_short_*.md`
- `runs/short-video/qc/*.qc.json`

不要提交：

- `cache/toutiao/auth_state.json`
- `Videos/short/toutiao/*.mp4`
- Playwright cookie/session 文件
