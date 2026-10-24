"""Declarative presets. Provider-specific contracts live here, not in the runner."""

import copy

from .config import APIError, json_object, validate_url

OPENAI_IMAGES = {
    "base_url": "https://api.openai.com/v1",
    "auth": "bearer",
    "max_images": 16,
    "generate": {
        "endpoint": "images/generations",
        "body": {
            "model": "{{model}}",
            "prompt": "{{prompt}}",
            "size": "{{size}}",
            "n": 1,
        },
    },
    "edit": {
        "endpoint": "images/edits",
        "format": "multipart",
        "file_field": "auto",
        "body": {
            "model": "{{model}}",
            "prompt": "{{prompt}}",
            "size": "{{size}}",
            "n": 1,
        },
    },
    "result_path": "/data",
}

GENERIC_ASYNC = {
    "auth": "bearer",
    "upload": {
        "endpoint": "uploads/images",
        "format": "multipart",
        "file_field": "file",
        "url_path": "/url",
    },
    "generate": {
        "endpoint": "images/generations",
        "body": {
            "model": "{{model}}",
            "prompt": "{{prompt}}",
            "async": True,
        },
    },
    "edit": {
        "endpoint": "images/edits",
        "body": {
            "model": "{{model}}",
            "prompt": "{{prompt}}",
            "images": "{{images}}",
            "async": True,
        },
    },
    "poll": {
        "endpoint": "tasks/{{task_id}}",
        "task_id_path": "/id",
        "status_path": "/status",
        "success_states": ["completed"],
        "failure_states": ["failed", "cancelled"],
        "error_path": "/fail_reason",
        "interval": 5,
    },
    "result_path": "/data",
}

APIKO = copy.deepcopy(GENERIC_ASYNC)
APIKO.update(
    {
        "base_url": "https://api.apiko.app/v1",
        "model": "nano-banana-2.1",
        "resolution": "1k",
        "max_images": 14,
        "max_upload_mb": 10,
    }
)
APIKO["upload"]["https_only"] = True
APIKO["poll"]["pending_states"] = ["queued", "in_progress"]
for operation in ("generate", "edit"):
    APIKO[operation]["body"].update(
        {"size": "{{size}}", "resolution": "{{resolution}}", "n": 1}
    )

PRESETS = {"OpenAI Images": OPENAI_IMAGES, "APIKO": APIKO}
PRESET_NAMES = ["APIKO", "OpenAI Images", "Custom / 自定义"]


def validate_profile(profile):
    profile = copy.deepcopy(profile)
    profile["base_url"] = validate_url(profile.get("base_url", ""))
    if profile.get("auth", "bearer") not in (
        "bearer",
        "x-api-key",
        "x-goog-api-key",
        "none",
    ):
        raise APIError("不支持的认证格式 / Unsupported authentication mode.")
    for name, default, minimum, maximum in [
        ("timeout", 900, 1, 3600),
        ("max_images", 64, 1, 64),
        ("max_upload_mb", 20, 1, 64),
    ]:
        value = profile.get(name, default)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not minimum <= value <= maximum
        ):
            raise APIError(
                f"{name}: 需要 {minimum}–{maximum} / Expected {minimum}–{maximum}."
            )
        profile[name] = value
    if not isinstance(profile.get("headers", {}), dict):
        raise APIError("headers 需要对象 / headers must be an object.")
    profile.setdefault("result_path", "")
    if not isinstance(profile["result_path"], str):
        raise APIError("result_path 需要文本 / result_path must be a string.")
    for operation in ("upload", "generate", "edit", "poll", "result_request"):
        spec = profile.get(operation)
        if spec is None:
            continue
        if (
            not isinstance(spec, dict)
            or not isinstance(spec.get("endpoint"), str)
            or not spec["endpoint"].strip()
        ):
            raise APIError(f"{operation}: 请填写 endpoint / endpoint is required.")
        spec.setdefault("format", "multipart" if operation == "upload" else "json")
        if spec.get(
            "method", "GET" if operation in ("poll", "result_request") else "POST"
        ) not in ("GET", "POST", "PUT", "PATCH"):
            raise APIError(f"{operation}: 不支持的请求方式 / Unsupported method.")
        if (
            spec.get("format", "json") not in ("json", "multipart")
            or not isinstance(spec.get("body", {}), dict)
            or not isinstance(spec.get("headers", {}), dict)
        ):
            raise APIError(
                f"{operation}: 请检查 format、body 和 headers / Check format, body and headers."
            )
    poll = profile.get("poll")
    if poll:
        for name in ("task_id_path", "status_path"):
            if not isinstance(poll.get(name), str) or not poll[name].startswith("/"):
                raise APIError(
                    f"poll.{name}: 请使用 JSON Pointer，如 /data/id / Use a JSON Pointer."
                )
        for name in ("success_states", "failure_states", "pending_states"):
            if not isinstance(poll.get(name, []), list):
                raise APIError(f"poll.{name}: 需要数组 / Expected an array.")
        interval = poll.get("interval", 5)
        if (
            isinstance(interval, bool)
            or not isinstance(interval, (int, float))
            or not 1 <= interval <= 60
        ):
            raise APIError("轮询间隔需要 1–60 秒 / Poll interval must be 1–60 seconds.")
    return profile


def custom_profile(base_url, settings_json, timeout=900):
    settings = json_object(settings_json, "Request profile / 流程配置")
    settings.update({"base_url": base_url, "timeout": timeout})
    return validate_profile(settings)


def preset_profile(name, custom=None):
    if custom is not None:
        return validate_profile(custom)
    if name not in PRESETS:
        raise APIError(
            "自定义平台请连接“API 流程配置” / Connect API Request Profile for a custom provider."
        )
    return validate_profile(PRESETS[name])
