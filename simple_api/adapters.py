import copy
import json
import math
import re
from urllib.parse import quote

from .config import APIError
from .images import data_url, decode_images, image_base64, mask_png, png_bytes
from .transport import dump_response, request_json


def merge(base, extra):
    result = copy.deepcopy(base)
    for key, value in extra.items():
        result[key] = (
            merge(result[key], value)
            if isinstance(value, dict) and isinstance(result.get(key), dict)
            else copy.deepcopy(value)
        )
    return result


def send(config, endpoint, body, options, files=None):
    body = merge(body, options.get("extra_body", {}))
    if body.get("stream"):
        raise APIError(
            "当前节点使用完整响应，请设 stream=false / Use stream=false for these nodes."
        )
    if files:
        body = {
            key: json.dumps(value, ensure_ascii=False)
            if isinstance(value, (dict, list, bool))
            else value
            for key, value in body.items()
            if value is not None
        }
    return request_json(
        config,
        options.get("endpoint") or endpoint,
        body,
        files=files,
        headers=options.get("headers"),
        timeout=options.get("timeout", 180),
    )


def model_name(model):
    if not isinstance(model, str) or not model.strip():
        raise APIError(
            "请填写平台提供的模型名 / Enter the model ID from your provider."
        )
    return model.strip()


def gemini_endpoint(model):
    return (
        "models/"
        + quote(model.removeprefix("models/"), safe="-._")
        + ":generateContent"
    )


def text_payload(config, model, prompt, images, options):
    system = options.get("system_prompt", "").strip()
    if config.protocol == "gemini":
        parts = [{"text": prompt}] + [
            {"inlineData": {"mimeType": "image/png", "data": image_base64(image)}}
            for image in images
        ]
        body = {"contents": [{"role": "user", "parts": parts}]}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return gemini_endpoint(model), body
    if config.protocol == "anthropic":
        content = [{"type": "text", "text": prompt}] + [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": image_base64(image),
                },
            }
            for image in images
        ]
        body = {
            "model": model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": content}],
        }
        if system:
            body["system"] = system
        return "messages", body
    if config.protocol == "responses":
        content = [{"type": "input_text", "text": prompt}] + [
            {"type": "input_image", "image_url": data_url(image)} for image in images
        ]
        body = {"model": model, "input": [{"role": "user", "content": content}]}
        if system:
            body["instructions"] = system
        return "responses", body
    content = (
        [{"type": "text", "text": prompt}]
        + [
            {"type": "image_url", "image_url": {"url": data_url(image)}}
            for image in images
        ]
        if images
        else prompt
    )
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": content}
    ]
    return "chat/completions", {"model": model, "messages": messages}


def extract_text(response):
    if not isinstance(response, dict):
        return ""
    if "choices" in response:
        choices = response.get("choices") or []
        message = choices[0].get("message", {}) if choices else {}
        content = message.get("content")
        if isinstance(content, str):
            return content
        text = "\n".join(
            part.get("text", "")
            for part in (content or [])
            if isinstance(part, dict) and part.get("type") in ("text", "output_text")
        )
        return text or message.get("refusal", "")
    if "candidates" in response:
        candidates = response.get("candidates") or []
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        return "\n".join(
            part["text"]
            for part in parts
            if part.get("text") and not part.get("thought")
        )
    if "output" in response:
        return "\n".join(
            part["text"]
            for item in response["output"]
            if item.get("type") == "message"
            for part in item.get("content", [])
            if part.get("type") == "output_text" and part.get("text")
        )
    if "content" in response:
        return "\n".join(
            part["text"]
            for part in response["content"]
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return response.get("output_text", "")


def request_text(config, model, prompt, images=(), options=None):
    options = options or {}
    endpoint, body = text_payload(config, model_name(model), prompt, images, options)
    response, secrets = send(config, endpoint, body, options)
    text = extract_text(response)
    if not text:
        raise APIError(
            "未返回文本，模型可能拒绝或响应格式不匹配 / No text returned; model refusal or unexpected response.\n"
            + dump_response(response, secrets)[:1500]
        )
    return text, dump_response(response, secrets)


def aspect_ratio(size):
    match = re.fullmatch(r"(\d+)[x:](\d+)", size)
    if not match:
        raise APIError(
            "Gemini 尺寸请填 auto、1:1、16:9 或宽x高 / For Gemini use auto, an aspect ratio, or width x height."
        )
    width, height = map(int, match.groups())
    if not width or not height:
        raise APIError("图像尺寸必须大于零 / Image dimensions must be positive.")
    divisor = math.gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def request_images(
    config, model, prompt, size="auto", count=1, images=(), mask=None, options=None
):
    options = options or {}
    model = model_name(model)
    if config.protocol == "anthropic":
        raise APIError(
            "Claude 不支持生成图像，请更换连接 / Claude does not generate images; choose another connection."
        )
    mode = options.get("image_api", "auto")
    if mode == "auto":
        mode = config.image_api
    size = size.strip()
    files = None
    if config.protocol == "gemini":
        if mask is not None:
            raise APIError(
                "Gemini 不接受此遮罩接口，请用文字描述编辑区域 / Gemini uses prompt-based editing; disconnect the mask."
            )
        if count != 1:
            raise APIError(
                "Gemini 每次请求一张，请将数量设为 1 / Set image count to 1 for Gemini."
            )
        endpoint, body = text_payload(config, model, prompt, images, options)
        body["generationConfig"] = {"responseModalities": ["TEXT", "IMAGE"]}
        if size and size != "auto":
            body["generationConfig"]["imageConfig"] = {
                "aspectRatio": aspect_ratio(size)
            }
    elif mode in ("chat", "responses"):
        if mask is not None:
            raise APIError("遮罩只适用于 Images 接口 / Masks require the Images API.")
        if mode == "responses":
            if count != 1:
                raise APIError(
                    "Responses 图像请求请将数量设为 1 / Set count to 1 for Responses image requests."
                )
            content = [{"type": "input_text", "text": prompt}] + [
                {"type": "input_image", "image_url": data_url(image)}
                for image in images
            ]
            tool = {"type": "image_generation"}
            if size and size != "auto":
                tool["size"] = size
            endpoint, body = (
                "responses",
                {
                    "model": model,
                    "input": [{"role": "user", "content": content}],
                    "tools": [tool],
                },
            )
            if options.get("system_prompt"):
                body["instructions"] = options["system_prompt"]
        else:
            content = [{"type": "text", "text": prompt}] + [
                {"type": "image_url", "image_url": {"url": data_url(image)}}
                for image in images
            ]
            messages = [{"role": "user", "content": content}]
            if options.get("system_prompt"):
                messages.insert(
                    0, {"role": "system", "content": options["system_prompt"]}
                )
            endpoint, body = (
                "chat/completions",
                {"model": model, "messages": messages, "modalities": ["image", "text"]},
            )
            if count != 1:
                body["n"] = count
            if size and size != "auto":
                body["image_config"] = {"aspect_ratio": aspect_ratio(size)}
    else:
        endpoint = "images/edits" if images else "images/generations"
        body = {"model": model, "prompt": prompt, "n": count}
        if size and size != "auto":
            body["size"] = size
        if images:
            image_field = options.get("image_field", "auto")
            if image_field == "auto":
                image_field = "image[]" if len(images) > 1 else "image"
            files = [
                (image_field, (f"image_{index + 1}.png", png_bytes(image), "image/png"))
                for index, image in enumerate(images)
            ]
            if mask is not None:
                files.append(
                    ("mask", ("mask.png", mask_png(mask, images[0]), "image/png"))
                )
    response, secrets = send(config, endpoint, body, options, files=files)
    try:
        output = decode_images(response, options.get("timeout", 180))
    except APIError as error:
        raise APIError(
            str(error) + "\n" + dump_response(response, secrets)[:1500]
        ) from None
    return output, extract_text(response), dump_response(response, secrets)


def select_path(value, path):
    """RFC 6901 JSON Pointer; numeric tokens work for arrays."""
    if not path:
        return value
    if not path.startswith("/"):
        raise APIError(
            "结果路径请用 JSON Pointer，如 /choices/0/message/content / Use a JSON Pointer path."
        )
    try:
        for part in path[1:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            value = value[int(part)] if isinstance(value, list) else value[part]
        return value
    except (KeyError, IndexError, TypeError, ValueError):
        raise APIError(
            "结果路径不存在，请检查响应 JSON / Result path not found; check response JSON."
        ) from None


def template_body(value, prompt, model, images):
    replacements = {"{{prompt}}": prompt, "{{model}}": model}
    if isinstance(value, str):
        if value in ("{{images}}", "{{images_base64}}"):
            return [
                data_url(image) if value == "{{images}}" else image_base64(image)
                for image in images
            ]
        for marker, content in replacements.items():
            value = value.replace(marker, content)
        return value
    if isinstance(value, dict):
        return {
            key: template_body(item, prompt, model, images)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [template_body(item, prompt, model, images) for item in value]
    return value
