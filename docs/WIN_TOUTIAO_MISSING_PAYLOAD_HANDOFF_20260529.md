# WIN 今日头条 missing_payload 交接记录 2026-05-29

## 目标

继续处理当前今日头条收藏夹里的 `18 missing_payload` 视频。不考虑从手机 App 导出，继续走 Web 端自动化。

> **2026-05-29 更新：MAC 已完成批量下载验证，WIN 直接执行 preprocess + synthesize。**

## MAC 端已完成

1. 已确认历史短视频 pipeline 不需要重做：
   - 当前历史 payload/Markdown 已对齐到 `67/67`。
   - 原唯一 `payload_only` 已用 deterministic fallback 生成 Markdown 并通过 `split-pack` QC。
2. 已新增收藏夹分类、source-card、reconcile、missing 队列脚本：
3. **已完成 18 条 missing_payload 批量下载（2026-05-29）：**
   - 17/18 成功（mobile-playwright-capture）：`group/` 和 `item/` URL 格式均可。
   - 1 条失败：`toutiao-7618104338006737418`（#睡觉#好物推荐），页面重定向为 article 页无视频 URL，Ixigua 端 404 已删除，确认放弃。
   - MAC 侧未做 preprocess（已停止 whisper，whisper 生成的临时 payload 已清除）。
   - **WIN 负责重新下载 17 条 MP4 并用 SenseVoice 做 preprocess。**
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

### Step 1：preprocess（SenseVoice，默认 backend）

下载成功后直接用默认 backend（不要设 TRANSCRIBE_BACKEND，WIN 的 SenseVoice 优先）：

```bat
python scripts\short_video_pipeline.py preprocess ^
  --videos-dir Videos\short\toutiao ^
  --skip-done
```

预期输出格式：

```
[1/17] preprocess Videos/short/toutiao/toutiao-7555789076176044582.mp4
  提取帧: ...
  检测: N 次幻灯片切换, M 次标注事件
  保留 K/N 帧 ...
  [SenseVoice] 检测到语言: zh ...
  wrote runs/short-video/preprocess/toutiao-7555789076176044582-xxxxxxxx.payload.json
```

### Step 2：synthesize dry-run（生成打包方案，不调用 Qwen）

preprocess 完成后立即跑：

```bat
python scripts\short_video_pipeline.py synthesize --dry-run --write-plan
```

计划文件写入：`runs/short-video/packs/pack-YYYYMMDD-HHMMSS.plan.json`

### Step 3：synthesize（调用 Qwen，MAC 审查后执行）

**不要自行运行本步骤，先推送 payload + plan，由 MAC 审查后决策。**

如 MAC 指示可执行：

```bat
python scripts\short_video_pipeline.py synthesize --write-plan
```

## 停止条件

立刻停止并回传日志，不要硬刷：

1. 连续 3 个队列 item 都没有捕获 `video/mp4`。
2. 出现验证码、登录态失效、访问过快提示。
3. `mobile-playwright-capture` 成功下载但 ffprobe 无法读取。
4. preprocess 已生成 payload，但 Qwen 合成/拆包失败。

## 回传材料

WIN 完成 preprocess 后提交并推送：

```bat
git add runs/short-video/preprocess/toutiao-*.payload.json
git add runs/short-video/preprocess/toutiao-*.frames.json
git add runs/short-video/preprocess/toutiao-*.transcript.txt
git add runs/short-video/short-video-progress.json
git add "runs/short-video/packs/pack-*.plan.json"
git commit -m "feat(toutiao): WIN preprocess 17 missing videos with SenseVoice"
git push
```

synthesize 完成后额外提交：

```bat
git add Markdowns/TTS_short_*.md
git add runs/short-video/qc/*.qc.json
git commit -m "feat(toutiao): synthesize 17 missing toutiao short videos"
git push
```

不要提交：

- `cache/toutiao/auth_state.json`
- `Videos/short/toutiao/*.mp4`
- Playwright cookie/session 文件
