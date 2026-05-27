# 今日头条收藏夹同步运行手册

> 目标：把网页版“今日头条收藏”里的短视频同步到本地 `Videos/short/toutiao/`，再交给短视频 Qwen pipeline 预处理和装包。同步器只下载，不自动调用 Qwen/Gemini。

## 1. 文件位置

```text
scripts/toutiao_login.py
scripts/toutiao_probe_favorites.py
scripts/toutiao_download_favorites.py
scripts/toutiao_common.py

cache/toutiao/auth_state.json
cache/toutiao/manifest.json
cache/toutiao/probes/*.json
Videos/short/toutiao/*.mp4
```

`cache/` 和 `Videos/` 已在 `.gitignore` 中，登录态和下载视频不会被提交。

## 2. 第一次登录

```bash
python3 scripts/toutiao_login.py
```

脚本会打开 Chromium。手动登录今日头条后，回到终端按 Enter，登录态会保存到：

```text
cache/toutiao/auth_state.json
```

如果默认首页不能触发登录，可指定登录入口：

```bash
python3 scripts/toutiao_login.py --login-url "https://www.toutiao.com/"
```

## 3. 探测收藏页

默认收藏页来自环境变量 `TOUTIAO_FAVORITES_URL`，未设置时使用：

```text
https://www.toutiao.com/c/user/favourite/
```

建议第一次显式传入你浏览器里能打开的收藏页 URL：

```bash
python3 scripts/toutiao_probe_favorites.py \
  --favorites-url "<你的今日头条收藏页URL>" \
  --headed \
  --screenshot \
  --update-manifest
```

输出：

```text
cache/toutiao/probes/favorites-*.json
cache/toutiao/probes/favorites-*.png
cache/toutiao/manifest.json
```

探测器会滚动页面，抽取看起来像视频详情页的链接，并记录网络候选 URL。若 `Items found: 0`，先打开 probe JSON 和 screenshot 看页面是否已登录、收藏页是否正确、或链接结构是否变化。

常用参数：

```bash
python3 scripts/toutiao_probe_favorites.py --scrolls 20 --update-manifest
python3 scripts/toutiao_probe_favorites.py --limit 20 --update-manifest
```

## 4. 下载收藏视频

先 dry-run：

```bash
python3 scripts/toutiao_download_favorites.py --new-only --limit 10 --dry-run
```

确认列表无误后下载：

```bash
python3 scripts/toutiao_download_favorites.py --new-only --limit 10
```

下载器优先使用 `yt-dlp`，并把 Playwright 登录态转换成临时 Netscape cookie 文件传给 `yt-dlp`。如果 `yt-dlp` 失败，会尝试 Playwright 打开详情页、监听 `.mp4/.m3u8` 请求，再用 `ffmpeg` 保存。

可强制优先 Playwright 捕获：

```bash
python3 scripts/toutiao_download_favorites.py --new-only --limit 10 --prefer-playwright
```

成功后 manifest 中对应记录会更新：

```json
{
  "download_status": "done",
  "local_path": "Videos/short/toutiao/toutiao-xxx.mp4",
  "download_method": "ytdlp"
}
```

## 5. 接短视频 pipeline

下载完成后，不要运行 `zhihuTTS.py` 主批处理。短视频进入新的 P0/P1 pipeline：

```bash
python3 scripts/short_video_pipeline.py preprocess --videos-dir Videos/short/toutiao
python3 scripts/short_video_pipeline.py synthesize --dry-run --write-plan
```

先用 mock 输出验证拆分/QC：

```bash
python3 scripts/short_video_pipeline.py call-pack \
  --plan runs/short-video/packs/pack-<ts>.plan.json \
  --pack-index 1 \
  --mock-output \
  --split
```

真实 Qwen packing 必须显式设置 `DASHSCOPE_API_KEY`，并去掉 `--mock-output`：

```bash
python3 scripts/short_video_pipeline.py call-pack \
  --plan runs/short-video/packs/pack-<ts>.plan.json \
  --pack-index 1 \
  --split
```

如果已经有 `*.output.md`，只想重新拆分和 QC：

```bash
python3 scripts/short_video_pipeline.py split-pack \
  --input-json runs/short-video/packs/pack-<ts>-001.input.json \
  --output-md runs/short-video/packs/pack-<ts>-001.output.md
```

## 6. 推荐日常流程

```bash
python3 scripts/toutiao_probe_favorites.py --update-manifest --scrolls 20
python3 scripts/toutiao_download_favorites.py --new-only --limit 100
python3 scripts/short_video_pipeline.py preprocess --videos-dir Videos/short/toutiao
python3 scripts/short_video_pipeline.py synthesize --dry-run --write-plan
```

不要把模型调用放进定时任务。定时任务只做收藏同步和下载，模型合成应手动触发或由后续显式队列控制。

## 7. 常见问题

### Items found 为 0

可能原因：

- 登录态失效。
- 收藏页 URL 不对。
- 页面未滚动加载出收藏项。
- 今日头条页面结构变化，链接不再包含 `/video/` 或 `/group/`。

处理：

```bash
python3 scripts/toutiao_login.py
python3 scripts/toutiao_probe_favorites.py --headed --screenshot --update-manifest
```

### yt-dlp 失败

先用 Playwright 兜底：

```bash
python3 scripts/toutiao_download_favorites.py --new-only --prefer-playwright --limit 5
```

如果仍失败，看 manifest 的 `last_error`，以及 probe JSON 中的 `network_candidates`。

### 下载重复

`--new-only` 会跳过 manifest 中 `download_status=done` 且本地文件存在的记录。若要重下，删除对应 `local_path` 文件，或手动把 manifest 里的 `download_status` 改回 `pending`。
