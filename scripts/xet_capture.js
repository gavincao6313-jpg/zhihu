/**
 * 小鹅通相关资料批量下载 — 浏览器控制台捕获脚本
 *
 * 使用步骤：
 *  1. 打开课程页面，确保已登录
 *  2. 打开 Chrome DevTools（F12）→ Console
 *  3. 粘贴本脚本全文，回车执行
 *  4. 点击页面"相关资料"按钮，等待文件列表完全加载（下拉到底部）
 *  5. 控制台执行：  xetDump()
 *  6. 将输出的 JSON 保存为  scripts/links.json
 *  7. 运行：  python scripts/xet_download_pdfs.py
 */

(function () {
  const CAP = { resources: [], apis: [] };

  /* ── 拦截 fetch ─────────────────────────────────────────── */
  const _fetch = window.fetch.bind(window);
  window.fetch = async function (input, init) {
    const url = typeof input === 'string' ? input : (input?.url ?? '');
    const res = await _fetch(input, init);
    if (isTarget(url)) res.clone().json().then(d => absorb(url, d)).catch(() => {});
    return res;
  };

  /* ── 拦截 XHR ───────────────────────────────────────────── */
  const _open = XMLHttpRequest.prototype.open;
  const _send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (m, u, ...r) {
    this._xurl = u; return _open.call(this, m, u, ...r);
  };
  XMLHttpRequest.prototype.send = function (...a) {
    this.addEventListener('load', function () {
      if (!isTarget(this._xurl ?? '')) return;
      try { absorb(this._xurl, JSON.parse(this.responseText)); } catch (_) {}
    });
    return _send.apply(this, a);
  };

  function isTarget(url) {
    return /resource|attach|download|file|column|product/i.test(url)
      && !/\.js|\.css|\.png|\.jpg|\.gif|\.woff|\.svg/i.test(url);
  }

  /* ── 从响应中递归提取文件条目 ────────────────────────────── */
  function absorb(url, data) {
    if (!url || !data) return;
    CAP.apis.push(url);
    walk(data, url);
  }

  function walk(node, src) {
    if (!node || typeof node !== 'object') return;
    if (Array.isArray(node)) { node.forEach(x => walk(x, src)); return; }

    const nameKey = ['name', 'title', 'file_name', 'resource_name', 'fileName'].find(k => node[k]);
    const idKey   = ['id', 'file_id', 'resource_id', 'attach_id', 'fileId'].find(k => node[k]);
    const urlKey  = ['url', 'download_url', 'file_url', 'resource_url',
                     'origin_url', 'downloadUrl', 'fileUrl'].find(k => node[k]);

    if ((nameKey || idKey) && (urlKey || idKey)) {
      const id    = idKey   ? node[idKey]   : null;
      const name  = nameKey ? node[nameKey] : `file_${id}`;
      const dlUrl = urlKey  ? node[urlKey]  : null;
      const key   = id ?? dlUrl ?? name;
      if (!CAP.resources.find(r => (r.id ?? r.url ?? r.name) === key)) {
        CAP.resources.push({ id, name, url: dlUrl, _raw: node, _src: src });
        console.log(`[xetCapture] #${CAP.resources.length} ${name}`);
      }
    }

    for (const v of Object.values(node)) {
      if (v && typeof v === 'object') walk(v, src);
    }
  }

  /* ── 公开导出函数 ────────────────────────────────────────── */
  window.xetDump = function () {
    if (!CAP.resources.length) {
      console.warn('[xetCapture] 0 条资源。捕获到的 API：');
      [...new Set(CAP.apis)].forEach(u => console.log(' ', u));
      return;
    }
    const out = JSON.stringify({
      capturedAt: new Date().toISOString(),
      total: CAP.resources.length,
      resources: CAP.resources.map(r => ({
        id: r.id,
        name: r.name,
        url: r.url,
        _src: r._src,
        _raw: r._raw,
      })),
      apis: [...new Set(CAP.apis)],
    }, null, 2);

    navigator.clipboard?.writeText(out)
      .then(() => console.log('[xetCapture] 已复制到剪贴板，保存为 scripts/links.json'))
      .catch(() => console.log('[xetCapture] 请手动复制上方 JSON'));

    console.log(out);
    return out;
  };

  window.xetScanDom = function () {
    const links = [];
    document.querySelectorAll('a[href]').forEach(a => {
      if (/\.pdf|download|resource/i.test(a.href))
        links.push({ href: a.href, text: a.textContent.trim() });
    });
    console.log('[xetCapture] DOM 扫描结果:', links);
    return links;
  };

  console.log('[xetCapture] ✅ 监听已启动');
  console.log('[xetCapture] → 请点击"相关资料"，滚动加载全部 84 个文件');
  console.log('[xetCapture] → 加载完毕后执行：xetDump()');
}());
