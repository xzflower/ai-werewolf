"""LLM API client with OpenAI-compatible chat completions."""

import os
from pathlib import Path

import httpx


def _load_env_file(path: str | None = None) -> None:
    """从 .env 文件加载环境变量（仅当对应变量尚未设置时）"""
    candidates = [
        path,
        os.path.expanduser("~/.hermes/.env"),
        os.path.join(os.getcwd(), ".env"),
    ]
    for env_path in candidates:
        if env_path and Path(env_path).exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip("\"'")
                    if key not in os.environ:
                        os.environ[key] = val


def _clear_proxy_env() -> None:
    """清除所有代理环境变量，防止 httpx 尝试使用 SOCKS 代理。"""
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(var, None)
    os.environ["NO_PROXY"] = "*"


def _make_client(timeout=120):
    """创建 httpx 客户端，确保无代理。"""
    _clear_proxy_env()
    return httpx.Client(timeout=timeout, proxy=None)


class LLMClient:
    """Client for OpenAI-compatible LLM chat completions API."""

    def __init__(self, base_url=None, api_key=None, model=None):
        _load_env_file()
        self.api_key = api_key or self._detect_api_key()
        self.base_url = (base_url or self._detect_base_url()).rstrip("/")
        self.model = model or self._detect_model()

    @staticmethod
    def _detect_api_key():
        for var in ("DEEPSEEK_API_KEY", "LLM_API_KEY", "GLM_API_KEY"):
            key = os.environ.get(var)
            if key and key != "***":
                return key
        return ""

    @staticmethod
    def _detect_base_url():
        url = os.environ.get("DEEPSEEK_BASE_URL")
        if url:
            return url
        url = os.environ.get("LLM_BASE_URL")
        if url:
            return url
        if os.environ.get("DEEPSEEK_API_KEY"):
            return "https://api.deepseek.com"
        if os.environ.get("GLM_API_KEY"):
            return "https://open.bigmodel.cn/api/paas/v4"
        return "https://api.deepseek.com"

    @staticmethod
    def _detect_model() -> str:
        if os.environ.get("DEEPSEEK_API_KEY"):
            return "deepseek-chat"
        if os.environ.get("GLM_API_KEY"):
            return "glm-4-plus"
        return "deepseek-chat"

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(self, messages, temperature, max_tokens):
        return {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

    def _extract_content(self, data):
        return data["choices"][0]["message"]["content"]

    def chat(self, messages, temperature=0.8, max_tokens=2000):
        """同步聊天接口，重试 3 次，超时 120 秒。"""
        url = f"{self.base_url}/chat/completions"
        payload = self._build_payload(messages, temperature, max_tokens)
        headers = self._headers()
        last_error = None

        for attempt in range(3):
            try:
                with _make_client() as client:
                    resp = client.post(url, json=payload, headers=headers)
                    resp.raise_for_status()
                    return self._extract_content(resp.json())
            except httpx.TimeoutException:
                last_error = RuntimeError("请求超时，请稍后重试")
            except httpx.HTTPStatusError as exc:
                last_error = RuntimeError(
                    f"API 返回错误 (HTTP {exc.response.status_code}): "
                    f"{exc.response.text[:200]}"
                )
            except httpx.RequestError as exc:
                last_error = RuntimeError(f"网络请求失败: {exc}")
            except (KeyError, IndexError) as exc:
                last_error = RuntimeError(f"解析响应失败: {exc}")

        raise last_error or RuntimeError("未知错误")

    async def chat_async(self, messages, temperature=0.8, max_tokens=2000):
        """异步聊天接口。"""
        url = f"{self.base_url}/chat/completions"
        payload = self._build_payload(messages, temperature, max_tokens)
        headers = self._headers()

        try:
            _clear_proxy_env()
            async with httpx.AsyncClient(timeout=120, proxy=None) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                return self._extract_content(resp.json())
        except httpx.TimeoutException:
            raise RuntimeError("请求超时，请稍后重试")
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"API 返回错误 (HTTP {exc.response.status_code}): "
                f"{exc.response.text[:200]}"
            )
        except httpx.RequestError as exc:
            raise RuntimeError(f"网络请求失败: {exc}")
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"解析响应失败: {exc}")
