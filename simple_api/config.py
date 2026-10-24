import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


class APIError(ValueError):
    """A short, actionable error that ComfyUI can show directly."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


# Presets are conveniences, not a model allowlist. Every URL is overridable.
PROVIDERS = {
    "Custom / 自定义": ("openai", ""),
    "OpenAI": ("openai", "https://api.openai.com/v1"),
    "OpenAI Responses": ("responses", "https://api.openai.com/v1"),
    "Gemini": ("gemini", "https://generativelanguage.googleapis.com/v1beta"),
    "Claude": ("anthropic", "https://api.anthropic.com/v1"),
    "DeepSeek": ("openai", "https://api.deepseek.com/v1"),
    "Qwen / 百炼": ("openai", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    "SiliconFlow / 硅基流动": ("openai", "https://api.siliconflow.cn/v1"),
    "OpenRouter": ("openai", "https://openrouter.ai/api/v1"),
    "Ollama": ("openai", "http://127.0.0.1:11434/v1"),
}
PROTOCOLS = ["auto", "openai", "responses", "gemini", "anthropic"]


def json_object(value, label="JSON"):
    try:
        result = json.loads(value or "{}") if isinstance(value, str) else value
    except (ValueError, TypeError):
        raise APIError(f"{label}: JSON 格式错误 / Invalid JSON.") from None
    if not isinstance(result, dict):
        raise APIError(f"{label}: 需要 JSON 对象 {{}} / Expected a JSON object.")
    return result


def resolve_secret(reference):
    value = (reference or "").strip()
    if value.startswith("env:"):
        name = value[4:]
        value = os.environ.get(name, "").strip()
        if not value:
            raise APIError(
                f"未设置环境变量 {name} / Environment variable {name} is missing."
            )
    elif value.startswith("key:"):
        try:
            path = Path(__file__).resolve().parent.parent / "api_keys.json"
            keys = json.loads(path.read_text(encoding="utf-8"))
            value = keys[value[4:]]
            if not isinstance(value, str) or not value.strip():
                raise ValueError()
            value = value.strip()
        except (OSError, ValueError, KeyError, TypeError):
            raise APIError(
                "本地密钥不存在，请检查 api_keys.json / Check your local api_keys.json."
            ) from None
    if "\r" in value or "\n" in value:
        raise APIError("密钥不能包含换行 / Credentials cannot contain newlines.")
    return value


def validate_url(value):
    try:
        parts = urlsplit(value)
        valid = parts.scheme in ("http", "https") and parts.hostname and parts.port != 0
    except ValueError:
        valid = False
    if not valid or parts.username or parts.password or parts.query or parts.fragment:
        raise APIError(
            "请填写完整 API 基础地址，不含密钥或查询参数 / Enter a full HTTP(S) base URL without credentials or query parameters."
        )
    path = parts.path.rstrip("/")
    if path.endswith(
        (
            "/chat/completions",
            "/responses",
            "/messages",
            "/images/generations",
            "/images/edits",
            ":generateContent",
        )
    ):
        raise APIError(
            "请填写基础地址，不要包含调用路径 / Enter the base URL without the operation path."
        )
    return value.rstrip("/")


@dataclass(frozen=True)
class Connection:
    protocol: str
    base_url: str
    credential: str = field(repr=False)
    image_api: str = "images"


def connection(provider, base_url="", api_key="", protocol="auto"):
    if provider not in PROVIDERS or protocol not in PROTOCOLS:
        raise APIError("未知平台或接口格式 / Unknown provider or protocol.")
    preset_protocol, preset_url = PROVIDERS[provider]
    return Connection(
        preset_protocol if protocol == "auto" else protocol,
        validate_url(base_url.strip() or preset_url),
        api_key,
        "chat" if provider == "OpenRouter" else "images",
    )
