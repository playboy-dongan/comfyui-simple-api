import base64
import io

import pytest
import torch
from PIL import Image

from simple_api.adapters import request_images, request_text
from simple_api.config import APIError, connection
from simple_api.nodes import APIRequest
from simple_api.transport import request_json


def config(server, protocol="openai"):
    return connection(
        "Custom / 自定义", server.url + "/v1", "test-secret-key", protocol
    )


@pytest.mark.parametrize(
    "protocol,endpoint,response,auth",
    [
        (
            "openai",
            "/v1/chat/completions",
            {"choices": [{"message": {"content": "回答"}}]},
            "Authorization",
        ),
        (
            "responses",
            "/v1/responses",
            {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "回答"}],
                    }
                ]
            },
            "Authorization",
        ),
        (
            "gemini",
            "/v1/models/test-model:generateContent",
            {"candidates": [{"content": {"parts": [{"text": "回答"}]}}]},
            "x-goog-api-key",
        ),
        (
            "anthropic",
            "/v1/messages",
            {"content": [{"type": "text", "text": "回答"}]},
            "x-api-key",
        ),
    ],
)
def test_text_native_protocols(api_server, protocol, endpoint, response, auth):
    api_server.reply(response)
    text, raw = request_text(
        config(api_server, protocol),
        "test-model",
        "你好",
        options={"system_prompt": "简洁回答"},
    )
    assert text == "回答"
    assert "回答" in raw
    sent = api_server.requests[0]
    assert sent["path"] == endpoint
    assert "test-secret-key" in sent["headers"][auth]
    if protocol == "openai":
        assert sent["json"]["messages"][0] == {"role": "system", "content": "简洁回答"}
        assert "temperature" not in sent["json"]
    if protocol == "responses":
        assert sent["json"]["instructions"] == "简洁回答"
    if protocol == "gemini":
        assert "key=" not in sent["path"]
        assert sent["json"]["systemInstruction"]["parts"][0]["text"] == "简洁回答"
    if protocol == "anthropic":
        assert sent["headers"]["anthropic-version"] == "2023-06-01"
        assert sent["json"]["max_tokens"] == 4096


@pytest.mark.parametrize("protocol", ["openai", "responses", "gemini", "anthropic"])
def test_vision_sends_every_image(api_server, image, protocol):
    responses = {
        "openai": {"choices": [{"message": {"content": "ok"}}]},
        "responses": {"output_text": "ok"},
        "gemini": {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
        "anthropic": {"content": [{"type": "text", "text": "ok"}]},
    }
    api_server.reply(responses[protocol])
    request_text(
        config(api_server, protocol),
        "model",
        "compare",
        [image, torch.zeros(1, 3, 5, 3)],
    )
    body = api_server.requests[0]["json"]
    if protocol == "gemini":
        content = body["contents"][0]["parts"]
        encoded = [item["inlineData"]["data"] for item in content[1:]]
    elif protocol == "responses":
        content = body["input"][0]["content"]
        encoded = [item["image_url"].split(",")[1] for item in content[1:]]
    else:
        content = body["messages"][0]["content"]
        encoded = [
            item["source"]["data"]
            if protocol == "anthropic"
            else item["image_url"]["url"].split(",")[1]
            for item in content[1:]
        ]
    assert len(content) == 3
    assert [
        Image.open(io.BytesIO(base64.b64decode(value))).size for value in encoded
    ] == [(6, 8), (5, 3)]


def test_image_generation_and_different_sizes(api_server, image_b64, image):
    from simple_api.images import image_base64

    api_server.reply(
        {"data": [{"b64_json": image_b64}, {"b64_json": image_base64(image)}]}
    )
    images, _text, _raw = request_images(
        config(api_server), "image-model", "cat", "1024x1024", 2
    )
    assert [tuple(item.shape) for item in images] == [(1, 5, 7, 3), (1, 8, 6, 3)]
    assert api_server.requests[0]["json"] == {
        "model": "image-model",
        "prompt": "cat",
        "n": 2,
        "size": "1024x1024",
    }


@pytest.mark.parametrize(
    "count,override,expected",
    [(1, "auto", "image"), (2, "auto", "image[]"), (2, "image", "image")],
)
def test_multipart_edit_fields(api_server, image, image_b64, count, override, expected):
    api_server.reply({"data": [{"b64_json": image_b64}]})
    request_images(
        config(api_server),
        "model",
        "edit",
        images=[image] * count,
        options={
            "image_field": override,
            "extra_body": {"quality": "high", "custom": {"x": 1}},
        },
    )
    sent = api_server.requests[0]
    assert sent["path"] == "/v1/images/edits"
    assert [part["name"] for part in sent["multipart"] if part["filename"]] == [
        expected
    ] * count
    assert {
        part["name"]: part["data"] for part in sent["multipart"] if not part["filename"]
    }["custom"] == b'{"x": 1}'


def test_mask_white_becomes_transparent(api_server, image, image_b64):
    mask = torch.zeros(1, 8, 6)
    mask[0, 0, 0] = 1
    api_server.reply({"data": [{"b64_json": image_b64}]})
    request_images(config(api_server), "model", "edit", images=[image], mask=mask)
    mask_data = next(
        part["data"]
        for part in api_server.requests[0]["multipart"]
        if part["name"] == "mask"
    )
    result = Image.open(io.BytesIO(mask_data))
    assert result.mode == "RGBA"
    assert result.getpixel((0, 0))[3] == 0
    assert result.getpixel((1, 1))[3] == 255


def test_mask_mismatch_stops_before_http(api_server, image):
    with pytest.raises(APIError, match="Mask must match"):
        request_images(
            config(api_server),
            "model",
            "edit",
            images=[image],
            mask=torch.zeros(1, 3, 3),
        )
    assert not api_server.requests


def test_gemini_image_edit_and_nested_options(api_server, image, image_b64):
    api_server.reply(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "done"},
                            {
                                "inlineData": {
                                    "mimeType": "image/png",
                                    "data": image_b64,
                                }
                            },
                        ]
                    }
                }
            ]
        }
    )
    images, text, _raw = request_images(
        config(api_server, "gemini"),
        "models/model",
        "edit",
        "1920x1080",
        images=[image, image],
        options={
            "extra_body": {"generationConfig": {"imageConfig": {"imageSize": "2K"}}}
        },
    )
    assert len(images) == 1 and text == "done"
    body = api_server.requests[0]["json"]
    assert body["generationConfig"] == {
        "responseModalities": ["TEXT", "IMAGE"],
        "imageConfig": {"aspectRatio": "16:9", "imageSize": "2K"},
    }
    assert len(body["contents"][0]["parts"]) == 3
    assert api_server.requests[0]["path"] == "/v1/models/model:generateContent"


@pytest.mark.parametrize("mode", ["chat", "responses"])
def test_alternative_image_apis(api_server, image_b64, image, mode):
    response = (
        {
            "choices": [
                {
                    "message": {
                        "content": "done",
                        "images": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": "data:image/png;base64," + image_b64
                                },
                            }
                        ],
                    }
                }
            ]
        }
        if mode == "chat"
        else {"output": [{"type": "image_generation_call", "result": image_b64}]}
    )
    api_server.reply(response)
    images, _, _ = request_images(
        config(api_server), "model", "edit", images=[image], options={"image_api": mode}
    )
    assert len(images) == 1
    body = api_server.requests[0]["json"]
    if mode == "chat":
        assert body["modalities"] == ["image", "text"]
        assert len(body["messages"][0]["content"]) == 2
    else:
        assert body["tools"] == [{"type": "image_generation"}]
        assert len(body["input"][0]["content"]) == 2


def test_image_url_download_without_api_auth(api_server, image_b64):
    api_server.reply({"data": [{"url": api_server.url + "/asset.png"}]})
    api_server.reply(base64.b64decode(image_b64))
    images, _, _ = request_images(config(api_server), "model", "cat")
    assert len(images) == 1
    assert api_server.requests[0]["headers"]["Authorization"]
    assert "Authorization" not in api_server.requests[1]["headers"]


def test_custom_request_quotes_images_and_pointer(api_server, image, image_b64):
    api_server.reply({"data": [{"url": "data:image/png;base64," + image_b64}]})
    result, _raw = APIRequest().execute(
        config(api_server),
        "POST",
        "custom",
        "model",
        'say "hi"\nnext',
        '{"prompt":"{{prompt}}","images":"{{images}}"}',
        "/data/0/url",
        image_set=[image, image],
    )
    assert result == "data:image/png;base64," + image_b64
    assert api_server.requests[0]["json"]["prompt"] == 'say "hi"\nnext'
    assert len(api_server.requests[0]["json"]["images"]) == 2


def test_custom_large_base64_result_remains_decodable(api_server):
    large_value = "A" * 9000
    api_server.reply({"data": [{"b64_json": large_value}]})
    result, raw = APIRequest().execute(
        config(api_server), "POST", "custom", "", "", "{}", "/data/0/b64_json"
    )
    assert result == large_value
    assert large_value not in raw


def test_custom_get_and_headers(api_server, monkeypatch):
    monkeypatch.setenv("TEST_HEADER_KEY", "header-secret")
    api_server.reply({"ok": True})
    result, _raw = APIRequest().execute(
        config(api_server),
        "GET",
        "models",
        "",
        "",
        '{"limit":2}',
        "/ok",
        options={"headers": {"X-Custom-Key": "env:TEST_HEADER_KEY"}},
    )
    assert result == "true"
    assert api_server.requests[0]["method"] == "GET"
    assert api_server.requests[0]["path"] == "/v1/models?limit=2"
    assert api_server.requests[0]["headers"]["X-Custom-Key"] == "header-secret"


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_errors_are_sanitized_and_never_retried(api_server, status):
    api_server.reply(
        {"error": {"message": "bad test-secret-key", "api_key": "another-secret"}},
        status,
    )
    with pytest.raises(APIError) as caught:
        request_json(config(api_server), "test", {})
    assert f"HTTP {status}" in str(caught.value)
    assert "test-secret-key" not in str(caught.value)
    assert "another-secret" not in str(caught.value)
    assert len(api_server.requests) == 1


def test_redirect_does_not_forward_key(api_server):
    api_server.reply({}, 307, {"Location": "https://elsewhere.invalid"})
    with pytest.raises(APIError, match="HTTP 307"):
        request_json(config(api_server), "test", {})
    assert len(api_server.requests) == 1


def test_success_with_invalid_json(api_server):
    api_server.reply(b"<html>not an API</html>")
    with pytest.raises(APIError, match="Expected JSON"):
        request_text(config(api_server), "model", "hello")


def test_empty_text_response_reports_cause(api_server):
    api_server.reply({"promptFeedback": {"blockReason": "SAFETY"}})
    with pytest.raises(APIError, match="SAFETY"):
        request_text(config(api_server, "gemini"), "model", "hello")


def test_empty_image_response_reports_cause(api_server):
    api_server.reply({"candidates": [{"finishReason": "SAFETY"}]})
    with pytest.raises(APIError, match="SAFETY"):
        request_images(config(api_server, "gemini"), "model", "hello")
