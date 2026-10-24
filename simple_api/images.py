import base64
import binascii
import io

import numpy as np
import torch
from PIL import Image, ImageOps, UnidentifiedImageError

from .config import APIError
from .transport import download_image


def collect_images(*inputs):
    """Keep individual sizes; do not resize unrelated reference images."""
    result = []
    for value in inputs:
        if value is None:
            continue
        if isinstance(value, (tuple, list)):
            result.extend(collect_images(*value))
            continue
        if (
            not isinstance(value, torch.Tensor)
            or value.ndim != 4
            or value.shape[-1] not in (1, 3, 4)
        ):
            raise APIError(
                "图像需要 ComfyUI IMAGE 格式 [B,H,W,C] / Expected ComfyUI IMAGE tensor."
            )
        result.extend(value[i : i + 1] for i in range(value.shape[0]))
    return result


def png_bytes(image):
    array = (image[0].detach().cpu().clamp(0, 1).numpy() * 255).round().astype(np.uint8)
    if array.shape[-1] == 1:
        array = array[..., 0]
    stream = io.BytesIO()
    Image.fromarray(array).save(stream, format="PNG")
    return stream.getvalue()


def image_base64(image):
    return base64.b64encode(png_bytes(image)).decode("ascii")


def data_url(image):
    return "data:image/png;base64," + image_base64(image)


def mask_png(mask, image):
    if mask.ndim == 2:
        mask = mask.unsqueeze(0)
    if (
        mask.ndim != 3
        or mask.shape[0] != 1
        or tuple(mask.shape[1:]) != tuple(image.shape[1:3])
    ):
        raise APIError(
            "遮罩需与第一张图同尺寸且仅一张 / Mask must match the first image and contain one frame."
        )
    # Comfy white = edit. OpenAI transparent alpha = edit.
    alpha = (
        ((1 - mask[0].detach().cpu().clamp(0, 1).numpy()) * 255)
        .round()
        .astype(np.uint8)
    )
    rgba = np.zeros((*alpha.shape, 4), dtype=np.uint8)
    rgba[..., 3] = alpha
    stream = io.BytesIO()
    Image.fromarray(rgba).save(stream, format="PNG")
    return stream.getvalue()


def decode_image(value, timeout=180):
    try:
        if value.startswith(("http://", "https://")):
            raw = download_image(value, timeout)
        else:
            raw = base64.b64decode(
                value.split(",", 1)[1] if value.startswith("data:") else value,
                validate=True,
            )
        with Image.open(io.BytesIO(raw)) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            return torch.from_numpy(
                np.asarray(image, dtype=np.float32).copy() / 255.0
            ).unsqueeze(0)
    except (
        ValueError,
        binascii.Error,
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
    ):
        raise APIError(
            "返回的图像无法解码 / Could not decode the returned image."
        ) from None


def extract_image_values(response):
    """Recognize standard Images, Gemini, Responses and multimodal-chat output."""
    values = []
    if isinstance(response, list):
        for item in response:
            values.extend(extract_image_values(item))
    elif isinstance(response, dict):
        if response.get("b64_json"):
            values.append(response["b64_json"])
        elif response.get("type") == "image_generation_call" and response.get("result"):
            values.append(response["result"])
        elif "inlineData" in response or "inline_data" in response:
            inline = response.get("inlineData", response.get("inline_data"))
            if inline.get("mimeType", inline.get("mime_type", "")).startswith("image/"):
                values.append(inline["data"])
        elif isinstance(response.get("url"), str):
            values.append(response["url"])
        elif isinstance(response.get("image_url"), str):
            values.append(response["image_url"])
        else:
            for key in (
                "data",
                "candidates",
                "content",
                "parts",
                "output",
                "choices",
                "message",
                "images",
                "image_url",
            ):
                if key in response:
                    values.extend(extract_image_values(response[key]))
    return values


def decode_images(response, timeout=180):
    values = extract_image_values(response)
    if not values:
        raise APIError(
            "接口未返回图像，请检查模型和响应 JSON / No images returned; check model and response JSON."
        )
    # IMAGE list lets Preview/Save Image process outputs with different dimensions.
    return [decode_image(value, timeout) for value in values]
