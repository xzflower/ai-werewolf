"""测试 LLM 调用"""
import sys
sys.path.insert(0, '/home/ubuntu/ai-werewolf')
from backend.llm.client import LLMClient

print("=== 默认检测 ===")
c = LLMClient()
print(f"Model: {c.model}, URL: {c.base_url}")
print(f"Key: {c.api_key[:8]}...")

print("\n=== 测试默认 URL ===")
try:
    r = c.chat([{"role": "user", "content": "用5个字回答：你好吗？"}], max_tokens=50)
    print(f"OK: {r[:60]}")
except Exception as e:
    print(f"Error: {str(e)[:120]}")

print("\n=== 测试 GLM Coding API ===")
try:
    c2 = LLMClient(base_url="https://open.bigmodel.cn/api/coding/paas/v4", model="GLM-4-Plus")
    r2 = c2.chat([{"role": "user", "content": "用5个字回答：你好吗？"}], max_tokens=50)
    print(f"OK: {r2[:60]}")
except Exception as e:
    print(f"Error: {str(e)[:120]}")
