import importlib.util
import inspect
import json
from pathlib import Path

import pytest
import torch

from simple_api.adapters import merge, select_path
from simple_api.config import (
    PROVIDERS,
    APIError,
    connection,
    json_object,
    resolve_secret,
)
from simple_api.images import collect_images, decode_image
from simple_api.nodes import NODE_CLASS_MAPPINGS, APIImages, APIShowText
from simple_api.transport import dump_response, endpoint_url

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("provider", list(PROVIDERS)[1:])
def test_official_presets(provider):
    result = connection(provider, api_key="hidden-secret")
    assert result.base_url.startswith("http")
    assert "hidden-secret" not in repr(result)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "host/v1",
        "file:///tmp/api",
        "https://user:pass@host/v1",
        "https://host/v1?key=secret",
        "https://host/v1/chat/completions",
        "https://host/v1/responses",
    ],
)
def test_bad_base_urls(url):
    with pytest.raises(APIError):
        connection("Custom / 自定义", url)


def test_environment_key_resolved_only_when_used(monkeypatch):
    cfg = connection("OpenAI", api_key="env:TEST_API_KEY")
    monkeypatch.setenv("TEST_API_KEY", "first")
    assert resolve_secret(cfg.credential) == "first"
    monkeypatch.setenv("TEST_API_KEY", "second")
    assert resolve_secret(cfg.credential) == "second"
    monkeypatch.delenv("TEST_API_KEY")
    with pytest.raises(APIError, match="missing"):
        resolve_secret(cfg.credential)


def test_local_key_file(monkeypatch, tmp_path):
    import simple_api.config as module

    (tmp_path / "api_keys.json").write_text('{"main":"local-secret"}')
    nested = tmp_path / "simple_api" / "config.py"
    monkeypatch.setattr(module, "__file__", str(nested))
    assert resolve_secret("key:main") == "local-secret"
    with pytest.raises(APIError, match="api_keys.json"):
        resolve_secret("key:missing")


@pytest.mark.parametrize("text", ["[]", "null", "bad", '"string"'])
def test_json_requires_object(text):
    with pytest.raises(APIError):
        json_object(text)


def test_collect_batches_preserves_order_and_sizes(image):
    wide = torch.ones(2, 3, 12, 3)
    output, count = APIImages().collect(image, image_set=[wide])
    assert count == 3
    assert [tuple(item.shape) for item in output] == [
        (1, 3, 12, 3),
        (1, 3, 12, 3),
        (1, 8, 6, 3),
    ]
    assert torch.equal(output[2], image)


def test_invalid_image_input():
    with pytest.raises(APIError, match="IMAGE"):
        collect_images(torch.zeros(3, 5, 5))


def test_decode_invalid_image():
    with pytest.raises(APIError, match="decode"):
        decode_image("not an image")


def test_redaction_keeps_usage_and_hides_large_values():
    output = json.loads(
        dump_response(
            {
                "api_key": "another-secret",
                "message": "hello known-secret",
                "usage": {"total_tokens": 10},
                "data": "A" * 5000,
            },
            ["known-secret"],
        )
    )
    assert output["api_key"] == "[redacted]"
    assert output["message"] == "hello [redacted]"
    assert output["usage"]["total_tokens"] == 10
    assert len(output["data"]) < 100


def test_endpoint_rejects_other_origin():
    cfg = connection("OpenAI")
    with pytest.raises(APIError, match="origin"):
        endpoint_url(cfg, "https://other.invalid/capture")
    assert endpoint_url(cfg, "images/edits") == "https://api.openai.com/v1/images/edits"


def test_json_pointer_and_deep_merge():
    assert select_path({"a/b": [{"~x": "ok"}]}, "/a~1b/0/~0x") == "ok"
    with pytest.raises(APIError, match="not found"):
        select_path({}, "/missing")
    with pytest.raises(APIError, match="JSON Pointer"):
        select_path({}, "data.0")
    assert merge({"a": {"x": 1, "z": 3}}, {"a": {"x": 2}}) == {"a": {"x": 2, "z": 3}}


def test_text_preview():
    assert APIShowText().show("hello") == {
        "ui": {"text": ["hello"]},
        "result": ("hello",),
    }


def test_comfyui_import_by_folder_name():
    spec = importlib.util.spec_from_file_location(
        "comfyui_simple_api_test",
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    package = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = package
    spec.loader.exec_module(package)
    assert len(package.NODE_CLASS_MAPPINGS) == 13
    assert (ROOT / package.WEB_DIRECTORY).is_dir()


@pytest.mark.parametrize("name,cls", NODE_CLASS_MAPPINGS.items())
def test_schema_function_arguments_and_locales(name, cls):
    schema = cls.INPUT_TYPES()
    parameters = inspect.signature(getattr(cls, cls.FUNCTION)).parameters
    inputs = {**schema.get("required", {}), **schema.get("optional", {})}
    assert set(inputs) <= set(parameters)
    assert len(cls.RETURN_NAMES) == len(cls.RETURN_TYPES)
    if hasattr(cls, "OUTPUT_IS_LIST"):
        assert len(cls.OUTPUT_IS_LIST) == len(cls.RETURN_TYPES)
    for language in ("en", "zh"):
        localized = json.loads(
            (ROOT / "locales" / language / "nodeDefs.json").read_text()
        )[name]
        assert set(localized["inputs"]) == set(inputs)
        assert len(localized["outputs"]) == len(cls.RETURN_TYPES)
        assert localized["display_name"]


def test_example_workflows_are_wired_and_have_no_keys():
    examples = list((ROOT / "examples").glob("*.json"))
    assert len(examples) >= 5
    for path in examples:
        graph = json.loads(path.read_text())
        nodes = {node["id"]: node for node in graph["nodes"]}
        for link_id, source, slot, target, target_slot, kind in graph["links"]:
            assert nodes[source]["outputs"][slot]["type"] == kind
            assert nodes[target]["inputs"][target_slot]["type"] == kind
            assert nodes[target]["inputs"][target_slot]["link"] == link_id
            assert link_id in nodes[source]["outputs"][slot]["links"]
        assert "test-secret" not in path.read_text()
