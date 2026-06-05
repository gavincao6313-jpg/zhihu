/**
 * 小鹅通课程视频信息提取脚本
 *
 * 使用方法：
 * 1. 在浏览器中登录小鹅通，打开课程页面
 * 2. 按 F12 打开开发者工具，切换到 Console 标签
 * 3. 粘贴此脚本并回车运行
 * 4. 脚本会自动提取所有视频信息并下载 JSON 文件
 *
 * 支持的域名：*.h5.xet.pomoho.com, *.h5.xiaoeknow.com, *.h5.xet.citv.cn
 */

(async function () {
    'use strict';

    console.log('🔍 小鹅通视频信息提取器 v2.0');
    console.log('═'.repeat(50));

    // ========== 配置 ==========
    const CONFIG = {
        // 请求之间的延迟（毫秒），避免触发频率限制
        REQUEST_DELAY: 500,
        // 并发请求数
        CONCURRENCY: 3,
        // 输出文件名
        OUTPUT_FILE: 'zhihu_videos.json',
    };

    // ========== 状态 ==========
    const state = {
        courseInfo: null,
        resourceList: [],
        videoUrls: [],
        capturedAPIs: new Map(),  // 捕获的 API URL 模式 -> 响应示例
        errors: [],
    };

    // ========== 辅助函数 ==========
    function sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    function getAppId() {
        return window.APPID || window.__APPID ||
               (window.location.hostname.match(/^(app\w+?)\./) || [])[1] ||
               'unknown';
    }

    function getBaseURL() {
        return window.location.origin;
    }

    // ========== 网络请求拦截 ==========
    const capturedRequests = [];
    const originalFetch = window.fetch;
    const originalXHROpen = XMLHttpRequest.prototype.open;
    const originalXHRSend = XMLHttpRequest.prototype.send;

    // 拦截 fetch
    window.fetch = async function (...args) {
        const requestInfo = {
            url: typeof args[0] === 'string' ? args[0] : args[0]?.url,
            method: args[1]?.method || 'GET',
            body: args[1]?.body,
            timestamp: Date.now(),
            type: 'fetch',
        };

        const response = await originalFetch.apply(this, args);

        // 克隆响应以读取内容
        try {
            const clone = response.clone();
            const contentType = clone.headers.get('content-type') || '';
            if (contentType.includes('json')) {
                const data = await clone.json();
                requestInfo.responseData = data;
                capturedRequests.push(requestInfo);

                // 自动检测课程相关 API
                detectCourseAPI(requestInfo);
            }
        } catch (e) {
            // 无法克隆或解析，忽略
        }

        return response;
    };

    // 拦截 XMLHttpRequest
    XMLHttpRequest.prototype.open = function (method, url) {
        this._captureInfo = { method, url, timestamp: Date.now(), type: 'xhr' };
        return originalXHROpen.apply(this, arguments);
    };

    XMLHttpRequest.prototype.send = function (body) {
        const info = this._captureInfo;
        if (info) {
            info.body = body;
        }

        this.addEventListener('load', function () {
            if (!info) return;
            try {
                const contentType = this.getResponseHeader('content-type') || '';
                if (contentType.includes('json') && this.responseText) {
                    info.responseData = JSON.parse(this.responseText);
                    capturedRequests.push(info);
                    detectCourseAPI(info);
                }
            } catch (e) {
                // 忽略解析错误
            }
        });

        return originalXHRSend.apply(this, arguments);
    };

    // ========== API 自动检测 ==========
    function detectCourseAPI(requestInfo) {
        const url = requestInfo.url;
        const data = requestInfo.responseData;

        if (!data) return;

        // 检测课程结构 API（包含资源列表）
        if (data.data && (data.data.list || data.data.resources || data.data.chapters)) {
            const resources = data.data.list || data.data.resources ||
                            data.data.chapters?.flatMap(c => c.list || c.resources || []) || [];

            if (resources.length > 0 && (resources[0].resource_id || resources[0].id)) {
                const key = url.split('?')[0];
                if (!state.capturedAPIs.has('course_structure')) {
                    state.capturedAPIs.set('course_structure', {
                        url: key,
                        method: requestInfo.method,
                        body: requestInfo.body,
                        sampleResponse: data,
                    });
                    console.log(`✅ 检测到课程结构 API: ${key}`);
                    console.log(`   📦 包含 ${resources.length} 个资源`);
                }
            }
        }

        // 检测视频播放 URL API
        if (data.data && (data.data.play_url || data.data.video_url ||
                         data.data.videoUrl || data.data.m3u8_url ||
                         (data.data.video_urls && data.data.video_urls.encrypt))) {
            const key = url.split('?')[0];
            if (!state.capturedAPIs.has('video_play')) {
                state.capturedAPIs.set('video_play', {
                    url: key,
                    method: requestInfo.method,
                    body: requestInfo.body,
                    sampleResponse: data,
                });
                console.log(`✅ 检测到视频播放 API: ${key}`);
            }
        }
    }

    // ========== 页面数据提取 ==========
    function extractPageData() {
        console.log('\n📊 扫描页面数据...');

        // 检查 window 全局变量
        const globalsToCheck = [
            '__INITIAL_STATE__', '__DATA__', '__NUXT__', '__NEXT_DATA__',
            'pageData', 'courseData', 'columnData', 'resourceData',
            '__xiaoe_data__', '__xet_data__', 'g_config',
        ];

        for (const key of globalsToCheck) {
            if (window[key] !== undefined) {
                console.log(`   📌 发现 window.${key}`);
                try {
                    state.capturedAPIs.set('window_' + key, {
                        type: 'window_global',
                        key: key,
                        data: JSON.parse(JSON.stringify(window[key])),
                    });
                } catch (e) {
                    console.log(`   ⚠️ 无法序列化 window.${key}: ${e.message}`);
                }
            }
        }

        // 检查页面上的 <script> 标签中的 JSON 数据
        const scripts = document.querySelectorAll('script[type="application/json"], script[data-initial-state]');
        scripts.forEach((script, i) => {
            try {
                const data = JSON.parse(script.textContent);
                console.log(`   📌 发现内嵌 JSON 数据 (script[${i}])`);
                state.capturedAPIs.set('embedded_json_' + i, {
                    type: 'embedded_script',
                    data: data,
                });
            } catch (e) {
                // 忽略
            }
        });

        // 提取页面中的课程标题
        const titleSelectors = [
            '.title-row .title', '.course-title', '.column-title',
            'h1', '.header-title', '.product-title',
            '[class*="title"]', '[class*="Title"]',
        ];
        for (const sel of titleSelectors) {
            const el = document.querySelector(sel);
            if (el && el.textContent.trim().length > 3) {
                state.courseInfo = state.courseInfo || {};
                state.courseInfo.title = el.textContent.trim();
                console.log(`   📌 课程标题: ${state.courseInfo.title}`);
                break;
            }
        }
    }

    // ========== 分析课程列表 DOM ==========
    function extractResourceFromDOM() {
        console.log('\n📊 分析页面 DOM 中的课程列表...');

        // 小鹅通常见的课程列表 DOM 结构
        const selectors = [
            // 章节+课时列表容器
            '.chapter-list .chapter-item',
            '.course-list .course-item',
            '.resource-list .resource-item',
            '.catalog-list .catalog-item',
            // 通用的列表项
            '[class*="chapter"] [class*="item"]',
            '[class*="lesson"] [class*="item"]',
            '.catalogue-item',
            '.menu-item[data-id]',
            // 左侧导航项
            '.left-menu .menu-item',
            '.sidebar .nav-item',
            // 视频列表项
            '.video-item', '.video-list-item',
        ];

        const items = new Set();

        for (const sel of selectors) {
            try {
                const elements = document.querySelectorAll(sel);
                elements.forEach(el => {
                    // 尝试提取资源 ID
                    const resourceId = el.dataset?.resourceId ||
                                      el.dataset?.id ||
                                      el.getAttribute('data-resource-id') ||
                                      el.getAttribute('data-id') ||
                                      el.id;

                    // 提取标题
                    const titleEl = el.querySelector('[class*="title"], .name, h3, h4, span');
                    const title = titleEl ? titleEl.textContent.trim() : el.textContent.trim().substring(0, 100);

                    if (resourceId && resourceId.startsWith('p_')) {
                        items.add(JSON.stringify({
                            resource_id: resourceId,
                            title: title || '未知标题',
                            source: 'dom',
                        }));
                    }
                });

                if (elements.length > 0 && items.size > 0) {
                    console.log(`   ✅ 从选择器 "${sel}" 找到 ${elements.length} 个元素，提取了 ${items.size} 个资源`);
                    break;
                }
            } catch (e) {
                // 选择器无效，跳过
            }
        }

        return Array.from(items).map(s => JSON.parse(s));
    }

    // ========== 主动调用 API 获取课程结构 ==========
    async function callCourseAPI() {
        console.log('\n📡 尝试主动调用课程结构 API...');

        const appId = getAppId();
        const baseURL = getBaseURL();
        const columnId = window.location.pathname.split('/').pop();

        // 可能的 API 路径列表
        const apiPatterns = [
            // 小鹅通 H5 前端 API 常见模式
            `${baseURL}/xet/course/column/v1/detail?product_id=${columnId}&resource_type=6`,
            `${baseURL}/xet/course/column/v1/detail?column_id=${columnId}`,
            `${baseURL}/xet/course/v1/column/detail?product_id=${columnId}`,
            `${baseURL}/api/course/column/detail?product_id=${columnId}`,
            `${baseURL}/api/column/v1/detail?column_id=${columnId}`,
            `${baseURL}/course/api/column/detail?product_id=${columnId}`,
            // 带 app_id 的模式
            `${baseURL}/xet/course/column/v1/detail?app_id=${appId}&product_id=${columnId}`,
            // resource list
            `${baseURL}/xet/course/resource/v1/list?product_id=${columnId}&page=1&page_size=200`,
            `${baseURL}/api/course/resource/list?column_id=${columnId}&page=1&page_size=200`,
        ];

        for (const url of apiPatterns) {
            try {
                console.log(`   尝试: ${url.substring(0, 80)}...`);
                const resp = await fetch(url, { credentials: 'include' });

                if (resp.ok) {
                    const contentType = resp.headers.get('content-type') || '';
                    if (contentType.includes('json')) {
                        const data = await resp.json();
                        if (data.code === 0 || data.errcode === 0 || data.status === 'success' || data.data) {
                            console.log(`   ✅ 成功! API: ${url.split('?')[0]}`);
                            return { success: true, url, data };
                        }
                    }
                }
                console.log(`   ❌ 失败: HTTP ${resp.status}`);
            } catch (e) {
                console.log(`   ❌ 错误: ${e.message}`);
            }
            await sleep(300);
        }

        return { success: false };
    }

    // ========== 视频播放 URL 获取 ==========
    async function callVideoPlayAPI(resourceId, productId) {
        const baseURL = getBaseURL();

        const apiPatterns = [
            {
                url: `${baseURL}/xet/course/resource/v1/get_play_url`,
                method: 'POST',
                body: JSON.stringify({
                    resource_id: resourceId,
                    product_id: productId,
                }),
            },
            {
                url: `${baseURL}/xet/course/resource/v1/base_info?resource_id=${resourceId}&product_id=${productId}`,
                method: 'GET',
            },
            {
                url: `${baseURL}/api/course/resource/play?resource_id=${resourceId}`,
                method: 'GET',
            },
            {
                url: `${baseURL}/course/api/resource/play_url?resource_id=${resourceId}&product_id=${productId}`,
                method: 'GET',
            },
        ];

        for (const pattern of apiPatterns) {
            try {
                const options = {
                    method: pattern.method,
                    credentials: 'include',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                };
                if (pattern.body) {
                    options.body = pattern.body;
                }

                const resp = await fetch(pattern.url, options);
                if (resp.ok) {
                    const contentType = resp.headers.get('content-type') || '';
                    if (contentType.includes('json')) {
                        const data = await resp.json();
                        if (data.code === 0 || data.data) {
                            return { success: true, data };
                        }
                    }
                }
            } catch (e) {
                // 跳过
            }
        }

        return { success: false, error: '所有 API 模式都失败了' };
    }

    // ========== 解密 m3u8 URL ==========
    function decryptVideoUrl(encodedUrl) {
        // 小鹅通的 m3u8 URL 加密：Base64 + 特殊字符替换
        // 字符替换: @→1, #→2, $→3, %→4
        try {
            let decoded = encodedUrl
                .replace(/@/g, '1')
                .replace(/#/g, '2')
                .replace(/\$/g, '3')
                .replace(/%/g, '4');

            // Base64 解码
            const m3u8Url = atob(decoded);
            return { success: true, url: m3u8Url };
        } catch (e) {
            return { success: false, error: e.message, original: encodedUrl };
        }
    }

    // ========== 处理 API 响应数据 ==========
    function extractResourcesFromData(data) {
        let resources = [];

        if (!data || !data.data) return resources;

        const d = data.data;

        // 尝试多种数据结构
        if (Array.isArray(d)) {
            resources = d;
        } else if (d.list && Array.isArray(d.list)) {
            resources = d.list;
        } else if (d.resources && Array.isArray(d.resources)) {
            resources = d.resources;
        } else if (d.chapters) {
            // 章节结构
            for (const chapter of d.chapters) {
                if (chapter.list) {
                    resources = resources.concat(chapter.list);
                }
                if (chapter.resources) {
                    resources = resources.concat(chapter.resources);
                }
            }
        }

        // 标准化资源对象
        return resources.map(r => ({
            resource_id: r.resource_id || r.id || r.resourceId,
            title: r.resource_name || r.title || r.name || r.resource_title || '',
            type: r.resource_type || r.type || 3,  // 3 = 视频
            chapter_title: r.chapter_title || r.chapter_name || '',
            duration: r.duration || r.video_duration || 0,
            img_url: r.img_url || r.cover || '',
        }));
    }

    function extractPlayUrlFromData(data) {
        if (!data || !data.data) return null;

        const d = data.data;

        // 直接返回的播放 URL
        if (d.play_url) return { url: d.play_url, encrypted: false };
        if (d.video_url) return { url: d.video_url, encrypted: false };
        if (d.videoUrl) return { url: d.videoUrl, encrypted: false };
        if (d.m3u8_url) return { url: d.m3u8_url, encrypted: false };

        // 加密的视频 URL (小鹅通常见)
        if (d.video_urls && d.video_urls.encrypt) {
            const result = decryptVideoUrl(d.video_urls.encrypt);
            if (result.success) {
                return { url: result.url, encrypted: true };
            }
        }

        // 嵌套的 URL
        if (d.video_info && d.video_info.url) return { url: d.video_info.url, encrypted: false };
        if (d.resource && d.resource.play_url) return { url: d.resource.play_url, encrypted: false };

        return null;
    }

    // ========== 主流程 ==========
    async function main() {
        console.log(`\n📍 当前页面: ${window.location.href}`);
        console.log(`📍 App ID: ${getAppId()}`);

        // 1. 提取页面数据
        extractPageData();
        await sleep(1000);

        // 2. 尝试从 DOM 提取
        const domResources = extractResourceFromDOM();
        if (domResources.length > 0) {
            console.log(`\n✅ 从 DOM 提取到 ${domResources.length} 个资源`);
            state.resourceList = domResources;
        }

        // 3. 尝试调用课程结构 API
        const courseResult = await callCourseAPI();
        if (courseResult.success) {
            const resources = extractResourcesFromData(courseResult.data);
            if (resources.length > 0) {
                console.log(`✅ 从 API 获取到 ${resources.length} 个资源`);
                state.resourceList = resources;
            }
        }

        // 4. 从捕获的请求中提取
        for (const [key, apiInfo] of state.capturedAPIs) {
            if (apiInfo.sampleResponse) {
                const resources = extractResourcesFromData(apiInfo.sampleResponse);
                if (resources.length > state.resourceList.length) {
                    console.log(`✅ 从捕获的 ${key} 获取到 ${resources.length} 个资源`);
                    state.resourceList = resources;
                }
            }
        }

        if (state.resourceList.length === 0) {
            console.log('\n⚠️ 未能自动提取资源列表。');
            console.log('\n📋 请手动操作：');
            console.log('   1. 刷新页面，观察 Console 中的 API 捕获信息');
            console.log('   2. 展开左侧课程目录');
            console.log('   3. 点击任意一个视频播放');
            console.log('   4. 然后重新运行此脚本');
            console.log('\n💡 也可以运行 showCapturedAPIs() 查看已捕获的 API');

            window.showCapturedAPIs = () => {
                console.log('\n已捕获的 API 请求:');
                capturedRequests.forEach((req, i) => {
                    console.log(`[${i}] ${req.method} ${req.url.substring(0, 100)}`);
                    if (req.responseData) {
                        console.log('   Response keys:', Object.keys(req.responseData));
                    }
                });
            };

            window.state = state;
            window.capturedRequests = capturedRequests;
            return;
        }

        // 5. 显示找到的资源列表
        console.log(`\n📋 找到 ${state.resourceList.length} 个资源:`);
        const videoResources = state.resourceList.filter(r =>
            r.type === 3 || r.type === '3' || r.type === 'video' ||
            r.resource_type === 3 || r.resource_type === '3'
        );

        if (videoResources.length > 0) {
            console.log(`   🎬 其中 ${videoResources.length} 个是视频资源`);
            videoResources.slice(0, 5).forEach((r, i) => {
                console.log(`   [${i + 1}] ${r.title || r.resource_name || '未知'} (${r.resource_id})`);
            });
            if (videoResources.length > 5) {
                console.log(`   ... 还有 ${videoResources.length - 5} 个`);
            }
        } else {
            console.log('   （未区分资源类型，将处理全部资源）');
            state.resourceList.slice(0, 5).forEach((r, i) => {
                console.log(`   [${i + 1}] ${r.title || '未知'} (${r.resource_id})`);
            });
        }

        // 6. 询问用户是否提取视频播放 URL
        const toProcess = videoResources.length > 0 ? videoResources : state.resourceList;

        console.log(`\n🔄 现在将获取 ${toProcess.length} 个视频的播放 URL...`);
        console.log('   这可能需要几分钟，请耐心等待...');

        const productId = new URLSearchParams(window.location.search).get('product_id') || '';

        let completed = 0;
        let successCount = 0;

        // 使用并发控制
        const concurrency = CONFIG.CONCURRENCY;
        const queue = [...toProcess];

        async function processNext() {
            while (queue.length > 0) {
                const resource = queue.shift();
                const resourceId = resource.resource_id || resource.id;
                if (!resourceId) continue;

                try {
                    const result = await callVideoPlayAPI(resourceId, productId);
                    completed++;

                    if (result.success) {
                        successCount++;
                        const playUrl = extractPlayUrlFromData(result.data);
                        if (playUrl) {
                            state.videoUrls.push({
                                resource_id: resourceId,
                                title: resource.title || resource.resource_name || '',
                                chapter_title: resource.chapter_title || '',
                                play_url: playUrl.url,
                                encrypted: playUrl.encrypted,
                                api_response: result.data,
                            });
                        }
                    }

                    // 进度显示
                    if (completed % 10 === 0 || completed === toProcess.length) {
                        console.log(`   📦 进度: ${completed}/${toProcess.length}, 成功: ${successCount}`);
                    }
                } catch (e) {
                    completed++;
                    state.errors.push({
                        resource_id: resourceId,
                        error: e.message,
                    });
                }

                await sleep(CONFIG.REQUEST_DELAY);
            }
        }

        // 启动并发处理器
        const workers = Array.from({ length: concurrency }, () => processNext());
        await Promise.all(workers);

        console.log(`\n✅ 获取完成!`);
        console.log(`   总数: ${toProcess.length}`);
        console.log(`   成功获取播放URL: ${state.videoUrls.length}`);
        console.log(`   失败: ${state.errors.length}`);

        // 7. 生成并下载 JSON 文件
        if (state.videoUrls.length > 0 || state.resourceList.length > 0) {
            const exportData = {
                export_time: new Date().toISOString(),
                course_url: window.location.href,
                app_id: getAppId(),
                course_title: state.courseInfo?.title || document.title,
                total_videos: state.videoUrls.length || state.resourceList.length,
                // 优先使用已获取播放 URL 的视频
                videos: state.videoUrls.length > 0 ? state.videoUrls : state.resourceList.map(r => ({
                    resource_id: r.resource_id || r.id,
                    title: r.title || r.resource_name || '',
                    chapter_title: r.chapter_title || '',
                    play_url: null,  // 需要重新获取
                })),
                errors: state.errors,
                note: state.videoUrls.length === 0 ?
                    '⚠️ 播放 URL 获取失败，请查看 errors 字段。可能需要手动在页面点击视频以触发 API 调用，然后重新运行脚本。' : '',
            };

            const jsonStr = JSON.stringify(exportData, null, 2);
            console.log(`\n📄 导出数据大小: ${(jsonStr.length / 1024).toFixed(1)} KB`);

            // 下载 JSON 文件
            const blob = new Blob([jsonStr], { type: 'application/json' });
            const downloadUrl = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = downloadUrl;
            a.download = CONFIG.OUTPUT_FILE;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(downloadUrl);

            console.log(`\n✅ JSON 文件已下载: ${CONFIG.OUTPUT_FILE}`);
            console.log(`   请将此文件复制到 D:\\zhihu\\ 目录下`);
            console.log(`   然后运行: python download_videos.py`);
        }

        // 8. 打印摘要
        console.log('\n' + '═'.repeat(50));
        console.log('📊 提取摘要:');
        console.log(`   课程标题: ${state.courseInfo?.title || '未知'}`);
        console.log(`   视频总数: ${state.videoUrls.length || state.resourceList.length}`);
        console.log(`   成功获取 URL: ${state.videoUrls.length}`);
        if (state.errors.length > 0) {
            console.log(`   ⚠️ 失败: ${state.errors.length} 个`);
            console.log('   失败列表:', state.errors.slice(0, 5));
        }

        // 暴露状态到全局，方便调试
        window.__extractor_state = state;
        window.__extractor_requests = capturedRequests;
        console.log('\n💡 调试: 使用 __extractor_state 和 __extractor_requests 查看详细信息');
    }

    // ========== 运行 ==========
    try {
        await main();
    } catch (e) {
        console.error('❌ 脚本出错:', e);
        console.error('错误详情:', e.stack);
    }
})();
