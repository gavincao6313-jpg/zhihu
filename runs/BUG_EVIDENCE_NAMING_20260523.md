# BUG: 命名规则未传递到最终 Gemini 合成输出

**发现时间**: 2026-05-23  
**发现者**: Windows Runner  
**关联 commit**: `94b2a71` feat: stream output named by source type + date + title

## 症状

昨晚直播流（`stream-1`）的最终 Gemini 合成输出为：

```
Markdowns/TTS_stream-1.md   ← 实际输出
```

按照 `94b2a71` 引入的命名规则，应该命名为：

```
Markdowns/TTS_stream-live_20260522_<页面标题>.md   ← 预期输出
```

## 根因

`94b2a71` 只改了 `zhihuTTS_stream.py` 的内部 `base_stem` 回退逻辑，但命名链路有 **三个断点** 导致新规则从未生效：

### 断点 1：BAT 始终显式传 `--name`，覆盖了新规则

`run_zhihu_live.bat:122`:
```bat
"!PYTHON!" "!SCRIPT_DIR!zhihuTTS_stream.py" ^
  ... ^
  --name "!NAME!"     ← 始终传 --name
```

`zhihuTTS_stream.py:1030`（`94b2a71` 引入的代码）:
```python
base_stem = safe_name(args.name or (f"live_{_date}_{_title}" if _title else f"live_{_date}"))
#                     ^^^^^^^^ 显式传入的 --name 永远为真，新规则永不触发
```

### 断点 2：`build_stream_markdown.py:453` 输出路径未更新

```python
out_path = markdowns_dir / f"TTS_stream-{args.base}.md"
```

`args.base` 来自 BAT 的 `!NAME!`，直接沿用了 old-style 命名，完全没有 title/date 格式化逻辑。

### 断点 3：`run_zhihu_live.bat` 未被 `94b2a71` 修改

BAT 在 merge 和 synthesis 步骤中硬编码了 `--base "!NAME!"`：

```bat
rem line 135
"!PYTHON!" "!SCRIPT_DIR!scripts\merge_stream_chunks.py" ^
  --base "!NAME!" ^
  ...

rem line 156
"!PYTHON!" "!SCRIPT_DIR!scripts\build_stream_markdown.py" ^
  --base "!NAME!" ^
  ...
```

## 修复建议

方向 A：让 Python 侧完全负责命名，BAT 不传 `--name`/`--base`

1. `run_zhihu_live.bat`: 不再传 `--name` 给 `zhihuTTS_stream.py`
2. `zhihuTTS_stream.py`: 将生成的 `base_stem` 写入 runs 目录下某个 marker 文件（如 `stream-{base_stem}.name`）
3. `run_zhihu_live.bat`: 从 marker 文件读取 `base_stem`，用于后续 merge/synthesis 的 `--base`
4. `build_stream_markdown.py:453`: 输出路径使用 `--base` 传入的完整名称

方向 B：让 BAT 也实现命名规则（不推荐，逻辑重复）

## 影响范围

- 所有通过 `run_zhihu_live.bat` 启动的直播流，最终 Gemini 输出均使用 BAT 传入的 `--name` 而非 title 自动命名
- 仅当手动调用且不传 `--name` 时，新规则才生效
