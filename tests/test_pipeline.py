import base64
import copy
import io
import json

import pytest
import torch
from PIL import Image

from simple_api.config import APIError
from simple_api.nodes import APIAutoImage, APIAutoRequest
from simple_api.request_pipeline import (
    RequestPipeline,
    image_result,
    render,
    select_many,
)
from simple_api.request_profiles import (
    APIKO,
    OPENAI_IMAGES,
    validate_profile,
)

KEY = "test-provider-secret"


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def runner():
    clock = Clock()
    return RequestPipeline(clock=clock, sleep=clock.sleep), clock


def profile_for(server, preset=APIKO):
    return {**copy.deepcopy(preset), "base_url": server.url + "/v1"}


def completed(server):
    return {"status": "completed", "data": [{"url": server.url + "/output.png"}]}


def run_images(pipeline, profile, images=(), **kwargs):
    return pipeline.execute(
        profile,
        KEY,
        "",
        "combine references",
        images,
        process_result=image_result,
        **kwargs,
    )


def test_apiko_end_to_end_upload_poll_download(api_server, image, image_b64):
    pipeline, clock = runner()
    profile = profile_for(api_server)
    api_server.reply({"url": "https://uploads.example/a.png"})
    api_server.reply({"url": "https://uploads.example/b.png"})
    api_server.reply({"id": "task_123", "status": "queued"})
    api_server.reply({"id": "task_123", "status": "in_progress"})
    api_server.reply(completed(api_server))
    api_server.reply(base64.b64decode(image_b64))
    progress = []
    images, task_id, response = run_images(
        pipeline,
        profile,
        [image, torch.zeros(1, 3, 5, 3)],
        size="16:9",
        resolution="2k",
        progress=progress.append,
    )
    assert len(images) == 1 and tuple(images[0].shape) == (1, 5, 7, 3)
    assert task_id == "task_123" and progress[-1] == 100
    assert clock.now == 10
    sent = api_server.requests
    assert [request["path"] for request in sent] == [
        "/v1/uploads/images",
        "/v1/uploads/images",
        "/v1/images/edits",
        "/v1/tasks/task_123",
        "/v1/tasks/task_123",
        "/output.png",
    ]
    assert [
        Image.open(io.BytesIO(request["multipart"][0]["data"])).size
        for request in sent[:2]
    ] == [(6, 8), (5, 3)]
    assert all(request["multipart"][0]["name"] == "file" for request in sent[:2])
    assert sent[2]["json"] == {
        "model": "nano-banana-2.1",
        "prompt": "combine references",
        "images": ["https://uploads.example/a.png", "https://uploads.example/b.png"],
        "async": True,
        "resolution": "2k",
        "size": "16:9",
        "n": 1,
    }
    assert all(
        request["headers"]["Authorization"] == "Bearer " + KEY for request in sent[:-1]
    )
    assert "Authorization" not in sent[-1]["headers"]
    assert pipeline.pending is None and KEY not in response


def test_apiko_text_to_image_uses_same_general_pipeline(api_server, image_b64):
    pipeline, _ = runner()
    api_server.reply({"id": "task_1", "status": "queued"})
    api_server.reply(completed(api_server))
    api_server.reply(base64.b64decode(image_b64))
    run_images(pipeline, profile_for(api_server))
    request = api_server.requests[0]
    assert request["path"] == "/v1/images/generations"
    assert request["json"]["resolution"] == "1k"
    assert "size" not in request["json"] and "images" not in request["json"]


def test_different_provider_nested_upload_post_poll_and_separate_result(
    api_server, image, image_b64
):
    profile = {
        "base_url": api_server.url,
        "auth": "x-api-key",
        "model": "vendor/model",
        "upload": {
            "endpoint": "media",
            "file_field": "attachment",
            "body": {"filename": "{{filename}}"},
            "url_path": "/data/file/link",
        },
        "edit": {
            "endpoint": "jobs",
            "body": {
                "model_id": "{{model}}",
                "input": {"instruction": "{{prompt}}", "references": "{{images}}"},
            },
        },
        "poll": {
            "endpoint": "job-status",
            "method": "POST",
            "body": {"job": "{{task_id}}"},
            "task_id_path": "/payload/job",
            "status_path": "/data/state",
            "success_states": [2],
            "failure_states": [-1],
            "error_path": "/data/reason",
            "interval": 3,
        },
        "result_request": {"endpoint": "results/{{task_id}}"},
        "result_path": "/payload/pictures/*/src",
    }
    api_server.reply({"data": {"file": {"link": "https://media.example/a.png"}}})
    api_server.reply({"payload": {"job": "abc/123"}})
    api_server.reply({"data": {"state": 1}})
    api_server.reply({"data": {"state": 2}})
    api_server.reply({"payload": {"pictures": [{"src": api_server.url + "/result"}]}})
    api_server.reply(base64.b64decode(image_b64))
    pipeline, _ = runner()
    result, task_id, _ = run_images(pipeline, profile, [image])
    assert len(result) == 1 and task_id == "abc/123"
    assert api_server.requests[0]["multipart"][1]["name"] == "attachment"
    assert api_server.requests[1]["json"]["input"]["references"] == [
        "https://media.example/a.png"
    ]
    assert api_server.requests[2]["json"] == {"job": "abc/123"}
    assert api_server.requests[4]["path"] == "/results/abc%2F123"
    assert "Authorization" not in api_server.requests[0]["headers"]
    assert api_server.requests[0]["headers"]["x-api-key"] == KEY


def test_openai_synchronous_multipart_without_upload(api_server, image, image_b64):
    pipeline, _ = runner()
    profile = profile_for(api_server, OPENAI_IMAGES)
    profile["model"] = "image-model"
    api_server.reply({"data": [{"b64_json": image_b64}]})
    images, task_id, _ = run_images(pipeline, profile, [image, image])
    assert len(images) == 1 and task_id == ""
    assert len(api_server.requests) == 1
    sent = api_server.requests[0]
    assert sent["path"] == "/v1/images/edits"
    assert [part["name"] for part in sent["multipart"] if part["filename"]] == [
        "image[]",
        "image[]",
    ]


@pytest.mark.parametrize(
    "template", ["{{images}}", "{{images_base64}}", "{{image}}", "{{image_base64}}"]
)
def test_json_inline_images_without_upload(api_server, image, image_b64, template):
    profile = {
        "base_url": api_server.url,
        "auth": "none",
        "edit": {"endpoint": "inline-edit", "body": {"references": template}},
        "result_path": "/image",
    }
    api_server.reply({"image": image_b64})
    pipeline, _ = runner()
    run_images(pipeline, profile, [image])
    value = api_server.requests[0]["json"]["references"]
    value = value[0] if isinstance(value, list) else value
    if template in ("{{images}}", "{{image}}"):
        assert value.startswith("data:image/png;base64,")
        value = value.split(",", 1)[1]
    assert Image.open(io.BytesIO(base64.b64decode(value))).size == (6, 8)


def test_upload_json_base64_and_custom_auth_header(api_server, image, image_b64):
    profile = {
        "base_url": api_server.url,
        "auth": "none",
        "headers": {"X-Token": "{{api_key}}"},
        "upload": {
            "endpoint": "upload",
            "format": "json",
            "body": {"file": "{{image_base64}}"},
            "url_path": "/asset",
        },
        "edit": {
            "endpoint": "render",
            "body": {"reference": "{{image}}", "instruction": "{{prompt}}"},
        },
        "result_path": "/image",
    }
    api_server.reply({"asset": "https://assets.example/ref"})
    api_server.reply({"image": image_b64})
    pipeline, _ = runner()
    run_images(pipeline, profile, [image])
    assert Image.open(
        io.BytesIO(base64.b64decode(api_server.requests[0]["json"]["file"]))
    ).size == (6, 8)
    assert api_server.requests[1]["json"]["reference"] == "https://assets.example/ref"
    assert api_server.requests[1]["headers"]["X-Token"] == KEY


def test_poll_transient_failures_retry_without_resubmitting(api_server, image_b64):
    pipeline, _ = runner()
    api_server.reply({"id": "task_1", "status": "queued"})
    api_server.reply({"error": {"message": "busy"}}, 503)
    api_server.reply({"error": {"message": "slow down"}}, 429)
    api_server.reply(completed(api_server))
    api_server.reply(base64.b64decode(image_b64))
    run_images(pipeline, profile_for(api_server))
    assert sum(request["method"] == "POST" for request in api_server.requests) == 1


def test_timeout_resumes_accepted_job_when_deadline_extended(api_server, image_b64):
    pipeline, _ = runner()
    profile = profile_for(api_server)
    profile["timeout"] = 2
    api_server.reply({"id": "task_keep", "status": "queued"})
    with pytest.raises(APIError, match="task_keep"):
        run_images(pipeline, profile)
    assert pipeline.pending["id"] == "task_keep"
    profile["timeout"] = 30
    api_server.reply(completed(api_server))
    api_server.reply(base64.b64decode(image_b64))
    run_images(pipeline, profile)
    assert sum(request["method"] == "POST" for request in api_server.requests) == 1


def test_failed_image_download_reuses_completed_result(api_server, image_b64):
    pipeline, _ = runner()
    profile = profile_for(api_server)
    api_server.reply({"id": "task_keep", "status": "queued"})
    api_server.reply(completed(api_server))
    api_server.reply({}, 500)
    with pytest.raises(APIError, match="task_keep"):
        run_images(pipeline, profile)
    api_server.reply(base64.b64decode(image_b64))
    run_images(pipeline, profile)
    assert [request["path"] for request in api_server.requests] == [
        "/v1/images/generations",
        "/v1/tasks/task_keep",
        "/output.png",
        "/output.png",
    ]


def test_resumed_result_retains_custom_header_redaction(api_server):
    pipeline, _ = runner()
    profile = {
        "base_url": api_server.url,
        "auth": "none",
        "headers": {"X-Token": "custom-header-secret"},
        "generate": {"endpoint": "generate"},
        "result_path": "/value",
    }
    api_server.reply({"value": "custom-header-secret"})

    def fail_once(*args):
        raise APIError("parse failed")

    with pytest.raises(APIError, match="parse failed"):
        pipeline.execute(profile, "", "", "test", process_result=fail_once)
    result, _, raw = pipeline.execute(
        profile, "", "", "test", process_result=APIAutoRequest.process_result
    )
    assert result == "[redacted]" and "custom-header-secret" not in raw
    assert len(api_server.requests) == 1


def test_changed_image_mapping_creates_new_job(api_server, image):
    pipeline, _ = runner()
    profile = profile_for(api_server)
    profile["timeout"] = 2
    api_server.reply({"url": "https://assets.example/ref"})
    api_server.reply({"id": "first", "status": "queued"})
    with pytest.raises(APIError, match="first"):
        run_images(pipeline, profile, [image])
    profile["image_item"] = {"url": "{{image}}"}
    api_server.reply({"url": "https://assets.example/ref"})
    api_server.reply({"id": "second", "status": "queued"})
    with pytest.raises(APIError, match="second"):
        run_images(pipeline, profile, [image])
    assert api_server.requests[-1]["json"]["images"] == [
        {"url": "https://assets.example/ref"}
    ]


def test_interruption_preserves_job_for_resume(api_server, image_b64):
    pipeline, clock = runner()

    def interrupt():
        if clock.now >= 1:
            raise RuntimeError("cancelled")

    pipeline.interrupt = interrupt
    api_server.reply({"id": "task_keep", "status": "queued"})
    with pytest.raises(RuntimeError, match="cancelled"):
        run_images(pipeline, profile_for(api_server))
    pipeline.interrupt = lambda: None
    api_server.reply(completed(api_server))
    api_server.reply(base64.b64decode(image_b64))
    run_images(pipeline, profile_for(api_server))
    assert sum(request["method"] == "POST" for request in api_server.requests) == 1


def test_failure_state_stops_and_redacts_reason(api_server):
    pipeline, _ = runner()
    api_server.reply({"id": "task_bad", "status": "queued"})
    api_server.reply({"status": "failed", "fail_reason": "rejected " + KEY})
    with pytest.raises(APIError, match="Task failed") as caught:
        run_images(pipeline, profile_for(api_server))
    assert KEY not in str(caught.value)
    assert pipeline.pending is None and len(api_server.requests) == 2


def test_submit_is_not_automatically_retried(api_server):
    pipeline, _ = runner()
    api_server.reply({"error": {"message": "failed " + KEY}}, 503)
    with pytest.raises(APIError) as caught:
        run_images(pipeline, profile_for(api_server))
    assert len(api_server.requests) == 1 and KEY not in str(caught.value)


def test_reference_limit_checked_before_network(api_server, image):
    pipeline, _ = runner()
    with pytest.raises(APIError, match="14"):
        run_images(pipeline, profile_for(api_server), [image] * 15)
    assert not api_server.requests


def test_all_image_sizes_checked_before_upload(api_server, image, monkeypatch):
    import simple_api.request_pipeline as module

    raws = iter([b"small", b"x" * (1024 * 1024 + 1)])
    monkeypatch.setattr(module, "png_bytes", lambda image: next(raws))
    profile = profile_for(api_server)
    profile["max_upload_mb"] = 1
    pipeline, _ = runner()
    with pytest.raises(APIError, match="reference 2"):
        run_images(pipeline, profile, [image, image])
    assert not api_server.requests


@pytest.mark.parametrize(
    "url",
    ["data:image/png;base64,AAA", "http://example.com/ref.png", "/local/file.png"],
)
def test_apiko_rejects_invalid_uploaded_url(api_server, image, url):
    api_server.reply({"url": url})
    pipeline, _ = runner()
    with pytest.raises(APIError, match="image URL"):
        run_images(pipeline, profile_for(api_server), [image])
    assert len(api_server.requests) == 1


def test_general_request_can_return_text_or_structured_data(api_server):
    node = APIAutoRequest()
    node.pipeline, _ = runner()
    profile = {
        "base_url": api_server.url,
        "auth": "none",
        "generate": {"endpoint": "job", "body": {"input": "{{prompt}}"}},
        "result_path": "/answer",
    }
    api_server.reply({"answer": {"text": "hello", "n": 2}})
    result, task_id, _raw = node.execute(
        "Custom / 自定义", "", "", "hello", profile=profile
    )
    assert json.loads(result) == {"text": "hello", "n": 2} and task_id == ""


def test_image_node_accepts_batches_and_an_image_set(api_server, image, image_b64):
    node = APIAutoImage()
    node.pipeline, _ = runner()
    profile = profile_for(api_server, OPENAI_IMAGES)
    profile["model"] = "image-model"
    api_server.reply({"data": [{"b64_json": image_b64}]})
    output, _, _ = node.execute(
        "Custom / 自定义",
        KEY,
        "",
        "combine",
        image_1=image,
        image_2=image.repeat(2, 1, 1, 1),
        image_set=[image],
        profile=profile,
    )
    assert len(output) == 1
    assert (
        len([part for part in api_server.requests[0]["multipart"] if part["filename"]])
        == 4
    )


def test_profile_templates_and_json_pointers():
    assert render(
        {"size": "{{size}}", "prompt": "{{prompt}}"},
        {"size": None, "prompt": 'quote "\n'},
    ) == {"prompt": 'quote "\n'}
    assert select_many({"a/b": [{"~x": "ok"}, {"~x": "yes"}]}, "/a~1b/*/~0x") == [
        "ok",
        "yes",
    ]
    with pytest.raises(APIError, match="Unknown template"):
        render("{{unknown}}", {})
    with pytest.raises(APIError, match="Result path"):
        select_many({}, "/missing")


def test_per_image_object_templates_and_array_expansion(api_server, image, image_b64):
    profile = {
        "base_url": api_server.url,
        "auth": "x-goog-api-key",
        "image_item": {
            "inlineData": {"mimeType": "image/png", "data": "{{image_base64}}"}
        },
        "edit": {
            "endpoint": "generate",
            "body": {"contents": [{"parts": [{"text": "{{prompt}}"}, "{{images}}"]}]},
        },
        "result_path": "/output",
    }
    api_server.reply({"output": image_b64})
    pipeline, _ = runner()
    run_images(pipeline, profile, [image, torch.zeros(1, 3, 5, 3)])
    sent = api_server.requests[0]
    parts = sent["json"]["contents"][0]["parts"]
    assert len(parts) == 3 and parts[0] == {"text": "combine references"}
    assert [
        Image.open(io.BytesIO(base64.b64decode(part["inlineData"]["data"]))).size
        for part in parts[1:]
    ] == [(6, 8), (5, 3)]
    assert sent["headers"]["x-goog-api-key"] == KEY


@pytest.mark.parametrize(
    "extra",
    [
        {"poll": {"endpoint": "status"}},
        {"auth": "invalid"},
        {"timeout": 0},
        {"upload": {"endpoint": "upload", "format": "invalid"}},
    ],
)
def test_invalid_profiles_fail_before_execution(extra):
    with pytest.raises(APIError):
        validate_profile({"base_url": "https://example.com/v1", **extra})
