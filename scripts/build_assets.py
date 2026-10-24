"""Regenerate bilingual labels and portable ComfyUI example workflows."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from simple_api.nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

ZH_NODES = {
    "SAConnection": "API 连接",
    "SAText": "API 文本",
    "SAVision": "API 看图问答",
    "SAImage": "API 生成图像",
    "SAImageEdit": "API 多图编辑",
    "SAImages": "API 图像集合",
    "SAOptions": "API 高级选项",
    "SARequest": "API 通用请求",
    "SAImageDecode": "API 解码图像",
    "SAShowText": "API 显示文本",
}
ZH_INPUTS = {
    "provider": "平台",
    "base_url": "API 地址",
    "api_key": "API 密钥",
    "protocol": "接口格式",
    "connection": "连接",
    "model": "模型",
    "prompt": "提示词",
    "run_id": "重新请求编号",
    "options": "高级选项",
    "image_1": "图像 1",
    "image_2": "图像 2",
    "image_3": "图像 3",
    "image_4": "图像 4",
    "image_set": "图像集合",
    "mask": "遮罩",
    "size": "图像尺寸",
    "count": "数量",
    "system_prompt": "系统提示词",
    "timeout": "超时秒数",
    "endpoint": "接口路径",
    "extra_body": "额外参数 JSON",
    "headers": "请求头 JSON",
    "image_api": "图像接口",
    "image_field": "上传图片字段",
    "method": "请求方式",
    "body_json": "请求体 JSON",
    "result_path": "结果路径",
    "text": "文本",
    "image_data": "图像地址或 base64",
}
ZH_OUTPUTS = {
    **ZH_INPUTS,
    "images": "图像",
    "image": "图像",
    "response_json": "响应 JSON",
    "result": "结果",
}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def locales():
    for language in ("en", "zh"):
        nodes = {}
        for name, cls in NODE_CLASS_MAPPINGS.items():
            schema = cls.INPUT_TYPES()
            description = cls.DESCRIPTION.split(" / ", 1)
            info = {
                "display_name": ZH_NODES[name]
                if language == "zh"
                else NODE_DISPLAY_NAME_MAPPINGS[name],
                "description": description[-1] if language == "zh" else description[0],
                "inputs": {},
                "outputs": {},
            }
            for key, spec in {
                **schema.get("required", {}),
                **schema.get("optional", {}),
            }.items():
                tooltip = (
                    spec[1].get("tooltip", "").split(" / ", 1)
                    if len(spec) > 1
                    else [""]
                )
                info["inputs"][key] = {
                    "name": ZH_INPUTS.get(key, key)
                    if language == "zh"
                    else key.replace("_", " ").title(),
                    "tooltip": tooltip[-1] if language == "zh" else tooltip[0],
                }
            for index, output in enumerate(cls.RETURN_NAMES):
                info["outputs"][str(index)] = {
                    "name": ZH_OUTPUTS.get(output, output)
                    if language == "zh"
                    else output.replace("_", " ").title()
                }
            nodes[name] = info
        save(ROOT / "locales" / language / "nodeDefs.json", nodes)


def node(identifier, kind, pos, widgets=None):
    if kind in NODE_CLASS_MAPPINGS:
        cls = NODE_CLASS_MAPPINGS[kind]
        schema = cls.INPUT_TYPES()
        inputs = []
        widget_values = []
        for name, spec in {
            **schema.get("required", {}),
            **schema.get("optional", {}),
        }.items():
            widget = isinstance(spec[0], list) or spec[0] in (
                "INT",
                "FLOAT",
                "BOOLEAN",
                "STRING",
            )
            params = spec[1] if len(spec) > 1 else {}
            if widget and not params.get("forceInput"):
                widget_values.append(
                    (widgets or {}).get(
                        name,
                        params.get(
                            "default", spec[0][0] if isinstance(spec[0], list) else ""
                        ),
                    )
                )
            else:
                inputs.append({"name": name, "type": spec[0], "link": None})
        outputs = [
            {"name": name, "type": data_type, "links": []}
            for name, data_type in zip(cls.RETURN_NAMES, cls.RETURN_TYPES)
        ]
        size = [350, 310 if kind in ("SAImage", "SAImageEdit", "SARequest") else 245]
    elif kind == "LoadImage":
        inputs, outputs, widget_values, size = (
            [],
            [
                {"name": "IMAGE", "type": "IMAGE", "links": []},
                {"name": "MASK", "type": "MASK", "links": []},
            ],
            ["", "image"],
            [300, 310],
        )
    else:
        inputs, outputs, widget_values, size = (
            [{"name": "images", "type": "IMAGE", "link": None}],
            [],
            [],
            [320, 300],
        )
    return {
        "id": identifier,
        "type": kind,
        "pos": pos,
        "size": size,
        "flags": {},
        "order": identifier - 1,
        "mode": 0,
        "inputs": inputs,
        "outputs": outputs,
        "properties": {"Node name for S&R": kind},
        "widgets_values": widget_values,
    }


def workflow(nodes, links):
    encoded = []
    by_id = {item["id"]: item for item in nodes}
    for index, (source, source_slot, target, input_name) in enumerate(links, 1):
        target_slot = next(
            i
            for i, item in enumerate(by_id[target]["inputs"])
            if item["name"] == input_name
        )
        by_id[target]["inputs"][target_slot]["link"] = index
        by_id[source]["outputs"][source_slot]["links"].append(index)
        encoded.append(
            [
                index,
                source,
                source_slot,
                target,
                target_slot,
                by_id[source]["outputs"][source_slot]["type"],
            ]
        )
    return {
        "last_node_id": max(by_id),
        "last_link_id": len(links),
        "nodes": nodes,
        "links": encoded,
        "groups": [],
        "config": {},
        "extra": {"ds": {"scale": 0.8, "offset": [60, 60]}},
        "version": 0.4,
    }


def examples():
    shared = {
        "provider": "Custom / 自定义",
        "base_url": "https://your-api-host/v1",
        "api_key": "key:main",
    }
    for name, kind, prompt in [
        (
            "01-text",
            "SAText",
            "请把这段话改写得简洁易懂。 / Rewrite this text clearly.",
        ),
        (
            "02-generate-image",
            "SAImage",
            "一只坐在窗边的橘猫 / An orange cat by the window",
        ),
    ]:
        nodes = [
            node(1, "SAConnection", [0, 0], shared),
            node(2, kind, [410, 0], {"model": "YOUR_MODEL_ID", "prompt": prompt}),
            node(3, "SAShowText" if kind == "SAText" else "PreviewImage", [830, 0]),
        ]
        save(
            ROOT / "examples" / (name + ".json"),
            workflow(
                nodes,
                [
                    (1, 0, 2, "connection"),
                    (2, 0, 3, "text" if kind == "SAText" else "images"),
                ],
            ),
        )
    nodes = [
        node(1, "SAConnection", [0, 0], shared),
        node(2, "LoadImage", [0, 300]),
        node(3, "LoadImage", [0, 660]),
        node(
            4,
            "SAImageEdit",
            [420, 150],
            {
                "model": "YOUR_IMAGE_MODEL_ID",
                "prompt": "把图 1 的人物放到图 2 的场景中。 / Place the person in image 1 into the scene from image 2.",
            },
        ),
        node(5, "PreviewImage", [850, 150]),
    ]
    save(
        ROOT / "examples/03-multi-image-edit.json",
        workflow(
            nodes,
            [
                (1, 0, 4, "connection"),
                (2, 0, 4, "image_1"),
                (3, 0, 4, "image_2"),
                (4, 0, 5, "images"),
            ],
        ),
    )
    nodes = [
        node(1, "SAConnection", [0, 0], shared),
        node(2, "LoadImage", [0, 300]),
        node(
            3,
            "SAVision",
            [420, 0],
            {
                "model": "YOUR_VISION_MODEL_ID",
                "prompt": "简洁描述这张图片。 / Describe this image briefly.",
            },
        ),
        node(4, "SAShowText", [850, 0]),
    ]
    save(
        ROOT / "examples/04-vision.json",
        workflow(
            nodes, [(1, 0, 3, "connection"), (2, 0, 3, "image_1"), (3, 0, 4, "text")]
        ),
    )
    shared_gemini = {"provider": "Gemini", "base_url": "", "api_key": "key:gemini"}
    nodes = [
        node(1, "SAConnection", [0, 0], shared_gemini),
        node(
            2,
            "SAImage",
            [410, 0],
            {
                "model": "YOUR_GEMINI_IMAGE_MODEL_ID",
                "prompt": "一只橘猫的水彩插画 / A watercolor illustration of an orange cat",
                "size": "1:1",
            },
        ),
        node(3, "PreviewImage", [830, 0]),
    ]
    save(
        ROOT / "examples/05-gemini-image.json",
        workflow(nodes, [(1, 0, 2, "connection"), (2, 0, 3, "images")]),
    )


if __name__ == "__main__":
    locales()
    examples()
