import json
import re
from urllib.parse import urljoin, urlsplit

import requests

from .config import APIError, resolve_secret

MAX_RESPONSE_BYTES = 64 * 1024 * 1024
SENSITIVE = {
    "authorization",
    "apikey",
    "xapikey",
    "xgoogapikey",
    "token",
    "accesstoken",
    "secret",
    "password",
}


def redact(value, secrets=(), compact=False):
    if isinstance(value, dict):
        return {
            key: "[redacted]"
            if re.sub(r"[^a-z]", "", key.lower()) in SENSITIVE
            else redact(item, secrets, compact)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item, secrets, compact) for item in value]
    if isinstance(value, str):
        for secret in sorted((s for s in secrets if s), key=len, reverse=True):
            value = value.replace(secret, "[redacted]")
        if compact:
            value = re.sub(
                r"data:image/[^;,]+;base64,[A-Za-z0-9+/=\s]+", "[image data]", value
            )
        if compact and len(value) > 4096:
            return f"[large value omitted: {len(value)} characters]"
    return value


def dump_response(value, secrets=()):
    return json.dumps(
        redact(value, secrets, compact=True), ensure_ascii=False, indent=2
    )


def endpoint_url(config, endpoint):
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise APIError("接口路径不能为空 / Endpoint is required.")
    url = urljoin(config.base_url + "/", endpoint.lstrip("/"))
    parts, base = urlsplit(url), urlsplit(config.base_url)
    if (
        (parts.scheme, parts.hostname, parts.port)
        != (base.scheme, base.hostname, base.port)
        or parts.username
        or parts.password
        or parts.fragment
    ):
        raise APIError(
            "接口路径必须属于配置的平台地址 / Endpoint must belong to the configured API origin."
        )
    return url


def read_limited(response):
    chunks, size = [], 0
    for chunk in response.iter_content(65536):
        size += len(chunk)
        if size > MAX_RESPONSE_BYTES:
            raise APIError(
                "响应超过 64MB，请减少图片数量或尺寸 / Response exceeds 64MB; reduce image count or size."
            )
        chunks.append(chunk)
    return b"".join(chunks)


def request_json(
    config, endpoint, body=None, files=None, headers=None, timeout=180, method="POST"
):
    key = resolve_secret(config.credential)
    auth = {}
    if config.protocol == "anthropic":
        auth["anthropic-version"] = "2023-06-01"
        if key:
            auth["x-api-key"] = key
    elif key:
        auth["x-goog-api-key" if config.protocol == "gemini" else "Authorization"] = (
            key if config.protocol == "gemini" else f"Bearer {key}"
        )
    try:
        extra = {name: resolve_secret(value) for name, value in (headers or {}).items()}
    except (AttributeError, TypeError):
        raise APIError(
            "请求头的值必须是文本 / Header values must be strings."
        ) from None
    auth.update(extra)
    if files:
        # requests must generate the multipart boundary itself.
        auth = {
            name: value
            for name, value in auth.items()
            if name.lower() != "content-type"
        }
    secrets = [key] + list(extra.values())
    url = endpoint_url(config, endpoint)
    try:
        timeout = float(timeout)
        if not 1 <= timeout <= 3600:
            raise ValueError()
    except (ValueError, TypeError):
        raise APIError(
            "超时范围为 1–3600 秒 / Timeout must be 1–3600 seconds."
        ) from None
    try:
        with requests.Session() as session:  # noqa: SIM117 - make session lifetime explicit
            # No retries: a timed-out generation may already have been billed.
            with session.request(
                method,
                url,
                json=body if not files and method != "GET" else None,
                data=body if files else None,
                params=body if method == "GET" else None,
                files=files,
                headers=auth,
                timeout=(min(30, timeout), timeout),
                allow_redirects=False,
                stream=True,
            ) as response:
                raw = read_limited(response)
                try:
                    result = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    result = {"message": raw[:1500].decode("utf-8", errors="replace")}
                    if response.ok:
                        raise APIError(
                            "接口未返回 JSON，请检查 API 地址 / Expected JSON; check the API URL."
                        ) from None
                if not 200 <= response.status_code < 300:
                    hints = {
                        401: "密钥无效 / Invalid API key",
                        403: "无权限 / Access denied",
                        404: "地址或模型不存在 / Check endpoint and model",
                        429: "额度不足或请求过多 / Quota or rate limit",
                    }
                    hint = hints.get(response.status_code, "请求失败 / Request failed")
                    detail = dump_response(result, secrets)[:1500]
                    raise APIError(f"HTTP {response.status_code}: {hint}\n{detail}")
                if isinstance(result, dict) and result.get("error"):
                    raise APIError(dump_response(result["error"], secrets)[:1500])
                return result, secrets
    except requests.Timeout:
        raise APIError(
            "请求超时，服务端可能仍在处理；请检查后重试 / Request timed out; check provider status before retrying."
        ) from None
    except requests.RequestException:
        raise APIError(
            "连接失败，请检查地址、网络和代理 / Connection failed; check URL, network and proxy."
        ) from None


def download_image(url, timeout=180):
    parts = urlsplit(url)
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.username
        or parts.password
    ):
        raise APIError("返回的图像地址无效 / Invalid image URL in response.")
    try:
        # Intentionally no API headers on image/CDN downloads.
        with requests.get(
            url, timeout=(min(30, timeout), timeout), stream=True
        ) as response:
            response.raise_for_status()
            return read_limited(response)
    except requests.RequestException:
        raise APIError(
            "图像下载失败，请检查平台返回的地址 / Could not download the returned image."
        ) from None
