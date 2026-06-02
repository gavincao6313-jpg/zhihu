# 前端第二轮验证 — 真实数据加载

> **日期**: 2026-06-02 | **基于**: 6a88eff (跨 worktree 图片修复)

---

## 修复验证：跨 worktree 图片代理 ✅

`_locate_frame_file()` 自动扫描 ROOT.parent 兄弟目录，zhihu_url 下的帧文件可正常访问。

```
/api/frames?p=Videos/keyframes/seg_1780315322_000000/frame_00001.jpg
→ HTTP 200, image/jpeg, 11559 bytes ✅
```

---

## 真实数据矩阵

| Tab | 数据来源 | 状态 | 备注 |
|-----|------|:--:|------|
| Overview | manifest + QC JSON | ✅ | 完整元数据 |
| Chunks | manifest chunks / runs/*.md | ✅ | 170 chunks |
| QC | final-qc.json | ✅ | 警告、window_policy、frame_coverage |
| Transcript | combined-transcript.txt | ✅ | 51,551 字 |
| Markdown | Markdowns/*.md | ✅ | Gemini 217KB + Qwen 237KB |
| Keyframes | payload.json → 图片代理 | ✅ | 240 帧全部 200 OK |
| Plan | API POST /api/run-plans | ✅ | 命令预览 |
| Logs | — | ⏳ | 预留 UI |

---

## 新发现：帧类型数据缺失

原始 payload 中所有 436 帧的 `type` 和 `kind` 字段均为空：

```json
{ "type": "", "kind": "", "ts": "37.0" }
```

导致前端 Keyframes Tab 全部显示为 "context" 类型，slide/annotation 筛选器无法使用。

### 根因

`zhihuTTS_stream.py` 或 `extract_slides.py` 在提取帧时未写入类型分类字段。

### 修复方向

上游帧提取步骤增加帧分类：
- 差异度 > 阈值 → `slide`
- 有标注事件 → `annotation`  
- 其他 → `context`

这不是前端 bug，是数据管道问题。

---

> 🤖 Windows Run Owner | 2026-06-02
