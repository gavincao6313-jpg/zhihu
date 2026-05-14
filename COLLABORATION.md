# 协作流程

## 角色

| 电脑 | 职责 |
|------|------|
| Mac | 写代码。改 `.py`、`.gitignore` 等 |
| Windows | 跑脚本。只改 `.progress.json` |

## 规则

### Mac 不动 `.progress.json`
进度文件是 Windows 的专属文件。Mac 只看不写。

### Windows 不动代码
只改 `.progress.json` 并提交。不改 `.py` 文件。

## 流程

### Windows 每日运行

```bash
git pull
python zhihuTTS.py
git add .progress.json
git commit -m "progress: 更新处理进度"
git push
```

### Mac 日常开发

```bash
git pull   # 拉取最新进度
# ... 改代码 ...
git add / git commit / git push
```

## Windows 首次设置

```bash
git clone https://github.com/gavincao6313-jpg/zhihu.git
cd zhihu
pip install -r requirements.txt
```

然后把视频文件放进 `Videos/` 目录（这个目录不会被 git 跟踪），确保 `ffmpeg` 在 PATH 中，设置好环境变量：

| 变量 | 说明 |
|------|------|
| `OPENCLAW_GOOGLE_API_KEY` | Gemini API 密钥（必填） |
| `WHISPER_DEVICE` | `cpu` 或 `cuda`（有 NVIDIA 显卡用 cuda） |

## 冲突预防

- `.progress.json` → 只有 Windows 写 → 不冲突
- `.py` 代码文件 → 只有 Mac 写 → 不冲突
- `.gitattributes` 已配置 LF 换行符 → 跨平台换行符统一
