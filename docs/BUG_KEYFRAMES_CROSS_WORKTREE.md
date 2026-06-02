# Keyframes 图片代理 — 跨 worktree 路径问题

> **发现**: 2026-06-02 | **严重度**: P1

---

## 问题

`_resolve_frame_path()` (server.py line 228) 无法正确处理 WIN 端双 worktree 场景。

### 现场

```
ROOT = d:\zhihu\zhihu_file  (API 服务器启动目录)
Payload 中的帧路径 = D:\zhihu\zhihu_url\Videos\keyframes\seg_1780315322_000000\frame_00001.jpg

_resolve_frame_path() 执行:
  1. relative_to(ROOT) → ValueError  (zhihu_url ≠ zhihu_file)
  2. anchor 搜索 → 找到 "Videos" → 返回 "Videos/keyframes/..."
  3. /api/frames 端点查找: ROOT/Videos/keyframes/... 
     = d:\zhihu\zhihu_file\Videos\keyframes\...
     → ❌ 文件不存在（实际在 zhihu_url 下）
```

### 验证

```
目标帧: seg_1780315322_000000/frame_00001.jpg
  d:\zhihu\zhihu_file\Videos\keyframes\...  ❌ 不存在
  d:\zhihu\zhihu_url\Videos\keyframes\...   ✅ 存在
  
zhihu_file/Videos/keyframes:  1380 子目录（历史数据）
zhihu_url/Videos/keyframes:   170 子目录（昨天直播）
```

### 建议修复方向

方案 A: `_resolve_frame_path()` 检测到跨 worktree 路径时，回退到 `zhihu_url` 查找
方案 B: API 启动时接受 `--secondary-root` 参数，指向 `zhihu_url`
方案 C: 图片代理 `/api/frames` 先查 ROOT，失败则查 `PARENT_DIR/zhihu_url/`
