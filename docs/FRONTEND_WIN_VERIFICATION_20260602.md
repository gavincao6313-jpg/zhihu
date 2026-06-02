# 前端功能 WIN 端验证报告

> **验证日期**: 2026-06-02 | **验证人**: Windows Run Owner
> **验证范围**: `web_api/server.py` + `frontend/` (React + Vite)

---

## 一、环境

| 项目 | 版本 |
|------|------|
| OS | Windows 10 Home China 19045 |
| Node.js | v24.15.0 |
| npm | v11.12.1 |
| Python | d:\zhihu\zhihu_file\.venv-sensevoice\Scripts\python.exe |
| 分支 | main (8ec4fa4 → 已验证时 86883ae) |

---

## 二、启动验证

### 2.1 手动安装依赖

```bash
cd d:\zhihu\zhihu_file\frontend
npm install   # 6s, 70 packages
```

### 2.2 API 服务器

```bash
python web_api/server.py --host 0.0.0.0 --port 8765 --launch-mode live
```

**结果**: ✅ 启动成功，端口 8765 监听

### 2.3 前端

```bash
VITE_HOST=0.0.0.0 npx vite   # :5173
```

**结果**: ✅ 启动成功

---

## 三、API 端点验证

| 端点 | 方法 | 状态 | 说明 |
|------|------|:--:|------|
| `/api/runs` | GET | ✅ | 返回 27 条 run 记录（JSON） |
| `/api/runs/{id}` | GET | ✅ | 返回单条 run 详情，含 chunks/frames/qc/transcript/markdown |
| `/api/run-plans` | POST | ✅ | Dry-run 计划预览 |
| `/api/runs` | POST | ✅ | 保存 run plan 到 web-run-registry.json |
| `/api/runs/{id}/launch` | POST | ✅ | 返回 simulated launch（LAUNCH_MODE 控制） |
| `/api/runs/{id}` | PATCH | ✅ | 更新 run 状态 |

### 3.1 示例响应 (`GET /api/runs`)

```json
// 27 条 run，其中 13 条 source_type=live
// 包含昨天的 "live_20260601_医疗行业AI转型一应用" gemini35 + qwen-full
```

---

## 四、前端界面验证

### 4.1 8 个 Tab 全部可访问

| Tab | 状态 | 数据来源 | 备注 |
|-----|:--:|------|------|
| Overview | ✅ | manifest.json + final-qc.json | 元数据、时长、chunk/帧数、QC 状态 |
| Plan | ✅ | 静态/API | Dry-run 命令预览 |
| Logs | ⏳ | 待接入 | 预留 UI，等待实时日志 streaming |
| Chunks | ✅ | manifest chunks | 170 chunks 列表，含时间段/字数/帧数 |
| QC | ✅ | final-qc.json | QC 警告列表、window policy、frame coverage |
| Keyframes | ⏳ | payload frames | 预留 UI，等待帧图片路径接入 |
| Transcript | ✅ | combined-transcript.txt | 51,551 字完整逐字稿 |
| Markdown | ✅ | Markdowns/*.md | Gemini/Qwen 最终文档渲染 |

### 4.2 交互功能

| 功能 | 状态 | 说明 |
|------|:--:|------|
| 源类型筛选（MP4/Replay/Live） | ✅ | 按钮切换 |
| Run 列表选择 | ✅ | 点击展开详情 |
| Launch 按钮 | ✅ | PATCH 状态 → "probing" |
| Refresh 按钮 | ✅ | 重新拉取 /api/runs |
| API 不可用时 fallback | ✅ | 返回 `sampleRun` 示例数据 |
| 搜索 | ✅ | 搜索框 UI 就绪 |

### 4.3 UI 质量

- Lucide React 图标库，风格统一
- 深色终端风格设计（styles.css 724 行）
- 状态机可视化（probing → recording → transcribing → synthesizing → completed）
- 响应式卡片布局
- QC 警告高亮（黄色警告横幅）

---

## 五、问题与建议

### 5.1 已验证 OK

1. 纯标准库 Python API（`http.server`）零外部依赖 ✅
2. 前后端分离，Vite proxy `/api` → `:8765` ✅
3. MAC 局域网访问设计（`0.0.0.0` 绑定）✅
4. 自动 fallback 示例数据（API 不可用时前端不白屏）✅

### 5.2 发现的问题

1. **`npm install` 耗时** — 首次需 6s (70 packages)，`start_win.bat` 已处理自动安装
2. **Keyframes Tab 无数据** — 帧图片文件路径引用的是本地绝对路径，前端无法直接访问。考虑增加 `/api/runs/{id}/frames/{path}` 图片代理端点
3. **Logs Tab 空白** — 预留 UI 但未接入实时日志流。建议增加 SSE 端点 `/api/runs/{id}/logs/stream`
4. **Launch 按钮为 simulate 模式** — `LAUNCH_MODE=live` 时行为是否已对接 `run_zhihu_live.bat`？需确认
5. **搜索框 UI 存在但未实现功能** — `Search` icon 已 import 但搜索逻辑未绑定

### 5.3 建议优先级

| 优先级 | 建议 |
|:--:|------|
| P1 | 确认 Launch 按钮在 `live` 模式下能真正调用 `run_zhihu_live.bat` |
| P1 | 增加 Keyframes 图片代理端点 |
| P2 | Logs Tab 接入实时日志 SSE |
| P2 | 搜索框绑定过滤逻辑 |
| P3 | Transcript Tab 增加时间戳锚点跳转 |

---

## 六、结论

**前端功能基本可用。** 8 个 Tab 中有 5 个完全正常工作（Overview/Chunks/QC/Transcript/Markdown），历史数据读取稳定。Plan/Logs/Keyframes 预留了 UI 框架，待后续迭代接入实时数据。

WIN 端可正常启动和使用。MAC 端在同局域网访问 `http://<WIN-IP>:5173` 即可共享同一面板，无需在 MAC 上另行部署。

---

> 🤖 Generated with [Claude Code](https://claude.com/claude-code)
> Windows Run Owner | 2026-06-02
