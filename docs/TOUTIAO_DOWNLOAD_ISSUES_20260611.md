# Toutiao 收藏下载问题分析 — 2026-06-11 (v2)

## 问题总结

6 个问题，其中 1 个已解决（yt-dlp 版本），5 个待 Mac 修复。

---

## ✅ 已解决：yt-dlp 版本过旧

**现象：** 所有 `/video/` URL 报 "No video formats found"

**根因：** yt-dlp `2026.3.17` → 升级到 `2026.6.9` 后修复

**已验证：** `/video/` URL 在新版 yt-dlp 上可用（5/9 新条目下载成功）

**WIN 已执行：** `pip install --upgrade yt-dlp`（2026.3.17 → 2026.6.9）

---

## 🔴 待修复 1：URL 格式 fallback — /item/ /group/ → /video/

**commit `88453ba` 的 ixigua-mobile fallback（bug-166）方向正确，但未命中真正的修复路径。**

| URL 格式 | yt-dlp 2026.6.9 结果 |
|----------|---------------------|
| `/video/` | ✅ 可用（大部分） |
| `/item/` | ❌ 重定向到 ixigua → SSR_HYDRATED_DATA 失败 |
| `/group/` | ❌ 同上 |
| ixigua-mobile | ❌ 404（ID 不通用） |

**建议修复：** `download_record()` 中，yt-dlp 失败后的第一个 fallback 应该是把 `/item/` 和 `/group/` URL 转为 `/video/` URL（提取数字 ID → `https://www.toutiao.com/video/{id}/`），再重试 yt-dlp。这比 Playwright 和 ixigua-mobile 更快更可靠。

**WIN 已验证：** 75 个 manifest URL 已批量转换为 `/video/` 格式，5/9 新条目下载成功。

---

## 🔴 待修复 2：Cookie domain 过滤太窄

**位置：** `toutiao_login.py` L51、`_toutiao_auto_login.py`（WIN 临时脚本）

**现状：** 只过滤 `"toutiao.com" in domain`，漏掉关键 domain：

```
.toutiao.com        27 cookies  ← SSO 核心（sso_uid_tt, sessionid, passport_auth_status）
www.toutiao.com      7 cookies  ← 站点追踪 + x-web-secsdk-uid (session-only)
xxbg.snssdk.com      2 cookies  ← 字节 SDK（ttcid, tt_scid, 6月17日到期！）
.bytedance.com       1 cookie   ← ttwid 全域追踪
.www.toutiao.com     1 cookie   ← csrftoken
```

**建议修复：** 验证 cookie 时不过滤 domain，或至少包含 `toutiao.com` + `bytedance.com` + `snssdk.com`

---

## 🔴 待修复 3：认证 cookie 名字写错

**位置：** `toutiao_login.py` L52

```python
# 当前（bug-165 加的验证）：
auth_cookies = [c for c in toutiao_cookies if c.get("name") in ("sso_auth", "ttwid", "tt_webid", "MONITOR_WEB_ID")]

# 问题：sso_auth 和 MONITOR_WEB_ID 在实际 auth state 中不存在
```

**实际存在的认证 cookie：**
- `sso_uid_tt` / `sso_uid_tt_ss`
- `toutiao_sso_user` / `toutiao_sso_user_ss`
- `passport_auth_status` / `passport_auth_status_ss`
- `sessionid` / `sessionid_ss`
- `sid_guard` / `sid_tt`

**建议修复：** 改为 `("sso_uid_tt", "toutiao_sso_user", "passport_auth_status", "sessionid")`

---

## 🔴 待修复 4：session cookie expires=-1 导致 yt-dlp WARNING

**位置：** `toutiao_common.py` `storage_state_to_netscape_cookie_file()` L205

**现象：** 每次 yt-dlp 运行都报：
```
WARNING: skipping cookie file entry due to invalid expires at -1: 'www.toutiao.com\tFALSE\t/\tFALSE\t-1\tx-web-secsdk-uid\t...'
```

**根因：** `x-web-secsdk-uid` 是 session cookie（`expires = -1`），Netscape cookie 格式的 expires 字段被写入 `-1`，yt-dlp 认为无效。

**建议修复：** 对于 `expires <= 0` 的 cookie，写入一个远期时间戳（如 `9999999999`），或跳过 session cookie

---

## 🔴 待修复 5：`select_records()` 不过滤 `skip` 状态

**位置：** `toutiao_download_favorites.py` `select_records()` L114-125

```python
if new_only and record.get("download_status") == "done":
    continue
# 缺少：or record.get("download_status") == "skip"
```

导致 `--new-only` 每次都重试已标记为 skip 的条目（如 sslocal:// 文本帖、永久不可用的旧视频）。

---

## WIN 侧执行记录

| 步骤 | 结果 |
|------|------|
| 探针 JSON fallback（上次 session） | manifest 92 → 112（+20） |
| 探针 anchor 失效修复 | 代码被 Mac force push 回退 |
| yt-dlp 升级 | 2026.3.17 → 2026.6.9 |
| URL 批量转换 | 75 个 /item/ /group/ → /video/ |
| 登录（3 次尝试） | 最终用 auto-login 脚本 + 300s 超时回退成功 |
| 下载结果 | **5/9 成功**（+149MB），4 个仍失败（视频无 /video/ 格式） |
| 总计已下载 | 89/112（79.5%） |

## 临时文件（WIN 侧）

以下 `_*.py` 文件在 `zhihu_file/` 根目录，供 Mac 分析参考后删除：

- `_toutiao_auto_login.py` — 无交互自动检测登录（poll sso_uid_tt 等 cookie）
- `_download_pending.py` — 只下载 pending 状态的条目的独立脚本
- `_convert_urls.py` — 批量转换 /item/ /group/ URL 到 /video/
- `_check_cookies.py` — 列出所有 cookie domain
- `_test_ytdlp_v2.py` / `_test_video_url.py` / `_test_ixigua_mobile.py` — yt-dlp 测试脚本
- `_mark_old_skip.py` / `_fix_manifest.py` — manifest 维护脚本
- `_sync_toutiao_api.py` / `_sync_toutiao_api_v2.py` — API 分页尝试（失败，offset 被忽略）

## 验证数据

**yt-dlp 测试矩阵（2026.6.9）：**

| URL 示例 | 结果 |
|----------|------|
| `toutiao.com/video/7648192518505136168/` | ✅ 2 formats, 42s |
| `toutiao.com/video/7649305952604144128/` | ✅ 4 formats, 110s |
| `toutiao.com/video/7648842284393382440/` | ✅ 4 formats, 58s |
| `toutiao.com/video/7640124142305559094/` | ❌ 404 Not Found |
| `toutiao.com/item/*` | ❌ redirect → ixigua SSR_HYDRATED_DATA |
| `toutiao.com/group/*` | ❌ redirect → ixigua SSR_HYDRATED_DATA |
| `m.ixigua.com/video/{id}` | ❌ 404 或 SSR_HYDRATED_DATA |
