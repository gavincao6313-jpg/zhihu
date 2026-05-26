# 阿里百炼 Qwen3.6-Flash 接入分析

> 写给 MAC 端：替代 Gemini 的国内 API 方案，解决 free-tier 每日配额瓶颈。

---

## 一、为什么选 Qwen3.6-Flash

| 维度 | Gemini 3.5 Flash（当前） | Qwen3.6-Flash（推荐） |
|------|--------------------------|------------------------|
| 上下文 | 1M tokens | **1M tokens** |
| 多模态 | 文本 + 图片 + 视频 | 文本 + 图片 + 视频 |
| 单次最大图片 | 3000（实际上限更低） | **256 张** |
| 最大输出 | 65536 tokens | **64000 tokens** |
| 价格 | Free tier，250 RPD 硬限制 | **<0.8 元/百万 tokens**，批处理半价 |
| API 协议 | Google genai SDK（非标） | **OpenAI 兼容**（openai SDK 直接用） |
| 中文能力 | 良好 | 优秀（中文母语模型） |
| 新用户 | 无 | **7000 万 tokens 免费额度** |
| 图片格式 | 原始 JPEG bytes | Base64 data URL 或 HTTP URL |
| Thinking 模式 | `ThinkingConfig(thinking_budget=N)` | `extra_body={"enable_thinking": True}` |

**结论：Qwen 上下文相同、多模态能力相当、中文更强、OpenAI 兼容好接入、不受 Gemini RPD 限制。**

---

## 二、当前 Gemini 调用链路（需要改动的全貌）

### 2.1 核心调用函数（3 个）

| 文件 | 函数 | 行号 | 说明 |
|------|------|------|------|
| `utils.py` | `call_gemini(client, parts, label, ...)` | L51-136 | 通用封装，被 3 个脚本共用 |
| `zhihuTTS.py` | `_call_gemini_with_retry(client, parts, video_label)` | L138-227 | 视频处理专用（有模型降级逻辑） |
| `zhihuTTS_stream.py` | `_call_gemini_stream(client, parts, label)` | L114-174 | 直播流专用 |

三者核心逻辑相同：**创建 chat → `send_message(parts)` → 检测 MAX_TOKENS → `send_message("继续")`**。

### 2.2 Parts 构建函数（5 个）

所有函数都用相同的模式构建 `parts` 列表：

```python
parts = [PROMPT_TEXT, transcript_text]           # 文本部分
for frame in frames:
    parts.append(f"[Frame @1234s] type=slide")   # 标记文字
    parts.append(types.Part(                      # Google 专有类型
        inline_data=types.Blob(mime_type="image/jpeg", data=fp.read_bytes())
    ))
```

| 文件 | 函数 | 行号 |
|------|------|------|
| `scripts/build_stream_markdown.py` | `build_gemini_parts(transcript, frames)` | L198 |
| `build_final_markdown.py` | `build_replay_gemini_parts(payload, transcript_text)` | L111 |
| `scripts/live_sectioned_synthesis.py` | `_build_pass_a_parts(evidence)` | L223 |
| `zhihuTTS.py` | `process_video()` 内联 | L621-628 |
| `zhihuTTS_stream.py` | `build_stream_gemini_parts(manifest)` | L180 |

### 2.3 依赖关系图

```
zhihuTTS.py          ──→ _call_gemini_with_retry    (独立实现)
zhihuTTS_stream.py   ──→ _call_gemini_stream         (独立实现)
build_stream_markdown.py ──→ build_gemini_parts() ──→ utils.call_gemini()
build_final_markdown.py   ──→ build_replay_gemini_parts() ──→ utils.call_gemini()
live_sectioned_synthesis.py ──→ _build_pass_a_parts() ──→ utils.call_gemini()
```

---

## 三、Qwen API 调用方式

### 3.1 客户端初始化

```python
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["DASHSCOPE_API_KEY"],      # 阿里百炼 API Key
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)
```

### 3.2 多模态请求格式（OpenAI compatible）

```python
response = client.chat.completions.create(
    model="qwen3.6-flash",
    messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": "系统提示词..."},
            {"type": "text", "text": "逐字稿文本..."},
            {"type": "text", "text": "[Frame 00:15:20] type=slide"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,/9j/4AAQ..."}},
            # ... 更多文本+图片交替
        ]
    }],
    max_tokens=64000,
    extra_body={
        "enable_thinking": True,      # 开启思考模式（类似 Gemini ThinkingConfig）
        "thinking_budget": 4096,       # 思考 token 预算
    },
)
```

### 3.3 续写机制（不同于 Gemini）

| | Gemini | Qwen |
|------|--------|------|
| 截断信号 | `finish_reason == MAX_TOKENS` | `finish_reason == "length"` |
| 续写方式 | `chat.send_message("继续")` | 把上一轮的 response 拼到 messages 里重新请求 |
| 思考模式续写 | 不需要特殊处理 | 需要把 `reasoning_content` 一起传回 |

**Qwen 续写关键**：当 `finish_reason == "length"` 时，需要把模型返回的完整响应（包括 `reasoning_content` 和 `content`）作为 assistant message 追加到 messages 列表，再发一次请求。

```python
# Qwen 续写模式
messages = [{"role": "user", "content": [...]}]

response = client.chat.completions.create(model="qwen3.6-flash", messages=messages)
msg = response.choices[0].message

# 拼回 messages 继续
messages.append({"role": "assistant", "content": msg.content})
if hasattr(msg, "reasoning_content") and msg.reasoning_content:
    messages[-1]["reasoning_content"] = msg.reasoning_content

messages.append({"role": "user", "content": "继续"})
response2 = client.chat.completions.create(model="qwen3.6-flash", messages=messages)
```

### 3.4 图片 Base64 编码

```python
import base64

def image_to_data_url(path: Path) -> str:
    data = path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"
```

---

## 四、推荐实施方案

### 方案：适配器模式（最小改动，不改 callers）

**核心思路**：新增 `call_qwen` 函数，对外接受与 `call_gemini` 完全相同的 `parts` 列表格式，内部自动转换成 OpenAI Messages 格式。调用方代码零改动。

### 具体改动点

#### 4.1 `utils.py` — 新增两个函数

```python
# 新增 1：parts 列表 → OpenAI messages 转换器
def _parts_to_openai_messages(parts: list) -> list[dict]:
    """
    parts: list[str | google.genai.types.Part]
    返回: [{"role": "user", "content": [{"type": "text", ...}, {"type": "image_url", ...}]}]
    
    转换规则：
    - str → {"type": "text", "text": str}
    - Part(inline_data=Blob(mime_type="image/jpeg", data=bytes)) 
      → {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
    """

# 新增 2：Qwen 调用主函数
def call_qwen(
    client,       # openai.OpenAI 实例
    parts: list,  # 与 call_gemini 完全相同的格式
    label: str,
    *,
    model: str = "qwen3.6-flash",
    thinking_budget: int = 4096,
    max_retries: int = 6,
    retry_delay: int = 6,     # Dashscope 默认 100 QPM，比 Gemini 宽松
    max_continuations: int = 20,
    continuation_cooldown: int = 2,  # Qwen 不需要 6s，2s 即可
) -> str | None:
    """
    与 call_gemini 接口完全对齐。区别：
    - client 是 openai.OpenAI 而非 genai.Client
    - 续写方式不同（见 3.3）
    - thinking 通过 extra_body 传递
    """
```

#### 4.2 `build_stream_markdown.py` — 试点接入（推荐首个改造目标）

这是主直播合成管线，最适合先行验证。

改动：
- 新增 `--provider` 参数：`choices=("gemini", "qwen")`，默认 `"gemini"`
- 当 `--provider qwen` 时：
  - 使用 `openai.OpenAI` 创建 client（而非 `genai.Client`）
  - 调用 `call_qwen` 而非 `call_gemini`
  - 读取 `DASHSCOPE_API_KEY` 环境变量
- parts 构建逻辑 `build_gemini_parts()` **无需任何改动**

#### 4.3 后续推广

`build_stream_markdown.py` 验证通过后，按同样模式改造：
1. `build_final_markdown.py`（回放合成）
2. `live_sectioned_synthesis.py`（分段合成）
3. `zhihuTTS.py`、`zhihuTTS_stream.py`（最后改，改动量较大）

---

## 五、API 限制对比

| 限制项 | Gemini Free Tier | Qwen（Dashscope 按量付费） |
|--------|-----------------|---------------------------|
| RPM | 10 | 100 QPM（默认） |
| TPM | 250,000 | 无硬限制（1M 上下文） |
| RPD | 250 | 无限制 |
| 日处理视频量 | ~1-2 个 | 理论上不受限 |
| 每视频成本 | 0 | **约 0.05-0.2 元**（按 55K char + 200 张图片估算） |

**关键差异**：Gemini 免费但 RPD=250 是硬天花板。Qwen 付费但成本极低，一个 3 小时直播约 0.1 元，一天处理 10 个直播也不过 1-2 元。

---

## 六、风险与注意事项

1. **图片数量**：Qwen 单次最多 256 张，当前项目最多 499 张关键帧。超过 256 时需要在 `select_frames` 中将上限改为 256。
2. **Base64 开销**：每张图片 Base64 编码增加 ~33% 体积。100 张 100KB 的图 = ~13MB 请求体。需确认 Dashscope 的请求体大小限制。
3. **Thinking 模式 token 消耗**：`thinking_budget` 消耗的是上下文 tokens，需计入 1M 上限。
4. **兼容性**：parts 格式中检测 `types.Part` 用 duck-typing（`hasattr(part, "inline_data")`），避免硬依赖 Google SDK。
5. **重试策略差异**：Dashscope 的 429 返回格式与 Google 不同，`parse_retry_delay` 正则可能需要适配。
6. **输出质量**：Qwen 的中文输出风格可能与 Gemini 不同，prompt 可能需要微调。

---

## 七、环境变量

| 变量 | 用途 | 示例值 |
|------|------|--------|
| `DASHSCOPE_API_KEY` | 阿里百炼 API Key | `sk-xxxxxxxxxxxxxxxx` |
| `QWEN_MODEL`（可选） | 覆盖默认模型 | `qwen3.6-flash` |
| `GEMINI_API_KEY`（保留） | 现有 Gemini Key | 不变 |

从阿里云百炼控制台获取 Key：https://bailian.console.aliyun.com

---

## 八、参考链接

- 阿里百炼视觉理解文档：https://help.aliyun.com/zh/model-studio/vision-model
- Qwen3.6 发布公告：https://developer.aliyun.com/article/1728156
- OpenAI 兼容调用示例：https://help.aliyun.com/zh/model-studio/vision-model（同页）
- Dashscope API Key 获取：https://bailian.console.aliyun.com
