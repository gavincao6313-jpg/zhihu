import os
from google import genai

# 获取 API Key
api_key = os.environ.get('OPENCLAW_GOOGLE_API_KEY')
client = genai.Client(api_key=api_key)

print("正在扫描你的可用模型并进行实测...")

# 获取所有支持生成内容的模型
available_models = [m for m in client.models.list() if 'generateContent' in m.supported_actions]

for m in available_models:
    model_id = m.name.replace('models/', '')
    # 跳过明显不是对话模型的
    if 'embedding' in model_id or 'aqa' in model_id:
        continue
        
    try:
        # 发起一个微型测试请求
        response = client.models.generate_content(model=model_id, contents='hi')
        print(f"✅ 【发现可用模型】: {model_id}")
        print(f"   模型回复: {response.text[:20]}...")
        print(f"\n建议：请将 zhihuTTS.py 中的 model 参数改为 '{model_id}'")
        break # 找到第一个可用的就停止
    except Exception as e:
        # 打印简短报错，方便排查
        error_msg = str(e).split('.')[0]
        print(f"❌ {model_id} 不可用: {error_msg}")

else:
    print("\n很遗憾，扫描了所有模型，配额全部为 0。")