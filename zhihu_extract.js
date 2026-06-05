/**
 * 知乎训练营课程视频信息提取脚本
 *
 * 用法:
 * 1. 打开课程页面并登录
 * 2. F12 → Console → 粘贴运行
 * 3. 自动提取所有视频信息并下载 JSON 文件
 */

(async function() {
    'use strict';
    console.log('知乎课程提取器 v1');

    const productId = window.location.pathname.split('/')[5];
    console.log('课程ID:', productId);

    // 1. 尝试从页面 SSRed 数据提取
    let courseData = null;
    try {
        const scripts = document.querySelectorAll('script');
        for (const s of scripts) {
            if (s.id === 'js-initialData' && s.textContent) {
                const data = JSON.parse(s.textContent);
                console.log('找到 js-initialData');
                courseData = data;
                break;
            }
        }
    } catch(e) {}

    // 2. 尝试 appContext
    if (!courseData) {
        try {
            courseData = window.appContext;
            console.log('找到 appContext');
        } catch(e) {}
    }

    // 3. 尝试通过 API
    console.log('\n尝试调用课程目录 API...');

    // 复制 cookie 用于后续
    const cookie = document.cookie;
    console.log('\n=== COOKIE (复制备用) ===');
    console.log(cookie);
    console.log('=== COOKIE END ===\n');

    // 尝试各种 API
    const apiPatterns = [
        `/api/v4/market/training/product/${productId}/sections?limit=200`,
        `/api/v4/training/product/${productId}/sections`,
        `/api/v4/market/training-video/${productId}/sections`,
        `/api/v4/panshi/training/sections?training_id=${productId}`,
    ];

    for (const path of apiPatterns) {
        try {
            const url = 'https://www.zhihu.com' + path;
            console.log(`尝试: ${path}`);
            const resp = await fetch(url, { credentials: 'include' });
            if (resp.ok) {
                const data = await resp.json();
                console.log('成功!', JSON.stringify(data).substring(0, 500));

                // 提取视频列表
                let sections = [];
                const extractSections = (obj) => {
                    if (!obj || typeof obj !== 'object') return;
                    if (Array.isArray(obj)) {
                        obj.forEach(extractSections);
                        return;
                    }
                    if (obj.id && (obj.title || obj.name) && (obj.type === 'video' || obj.resource_id)) {
                        sections.push({
                            id: obj.id,
                            title: obj.title || obj.name,
                            resource_id: obj.resource_id || '',
                            chapter: obj.chapter_title || '',
                        });
                    }
                    Object.values(obj).forEach(extractSections);
                };
                extractSections(data);
                console.log(`提取到 ${sections.length} 节`);
                if (sections.length > 0) {
                    console.log('前3节:', sections.slice(0,3));
                }

                // 保存
                const blob = new Blob([JSON.stringify({product_id: productId, sections, cookie}, null, 2)], {type:'application/json'});
                const a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                a.download = 'zhihu_course.json';
                a.click();
                console.log('已下载 zhihu_course.json');
                return;
            }
        } catch(e) {
            console.log(`失败: ${e.message}`);
        }
    }

    // 如果 API 都不行，从 DOM 提取
    console.log('\nAPI方式失败，从页面DOM提取...');
    const sections = [];
    document.querySelectorAll('[class*=section], [class*=chapter], [class*=catalog], [class*=list] a[href*="training-video"]').forEach(a => {
        const match = a.href.match(/training-video\/\d+\/(\d+)/);
        if (match) {
            sections.push({
                id: match[1],
                title: a.textContent.trim(),
                url: a.href,
            });
        }
    });

    if (sections.length === 0) {
        // 也尝试 data-id 属性
        document.querySelectorAll('[data-id], [data-section-id]').forEach(el => {
            const id = el.dataset.id || el.dataset.sectionId;
            if (id && /^\d{19}$/.test(id)) {
                sections.push({
                    id: id,
                    title: el.textContent.trim().substring(0, 100),
                });
            }
        });
    }

    console.log(`DOM提取到 ${sections.length} 节`);
    if (sections.length > 0) {
        const blob = new Blob([JSON.stringify({product_id: productId, sections, cookie}, null, 2)], {type:'application/json'});
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'zhihu_course.json';
        a.click();
        console.log('已下载 zhihu_course.json');
    }

    console.log('\n如果以上都没提取到，请把 Cookie 发给我，我直接用 API 调。');
})();
