from .adapters import merge, request_images, request_text, select_path, template_body
from .config import PROTOCOLS, PROVIDERS, APIError, connection, json_object
from .images import collect_images, decode_image
from .transport import dump_response, redact, request_json

CATEGORY = "Simple API"


def string(default="", multiline=False, tooltip=""):
    return ("STRING", {"default": default, "multiline": multiline, "tooltip": tooltip})


MODEL = string(
    tooltip="Model ID from your provider; any supported ID is allowed. / 填写平台提供的模型名。"
)
PROMPT = string(
    multiline=True,
    tooltip="Write your request or connect a text output. / 输入要求，也可连接文本输出。",
)
RUN_ID = (
    "INT",
    {
        "default": 0,
        "min": 0,
        "max": 2147483647,
        "tooltip": "Change this value to request again with identical inputs. / 相同输入再次请求时，更改此数值。",
    },
)
IMAGE_PORTS = {
    "image_2": ("IMAGE",),
    "image_3": ("IMAGE",),
    "image_4": ("IMAGE",),
    "image_set": ("SA_IMAGES",),
}


class APIConnection:
    CATEGORY = CATEGORY
    FUNCTION = "build"
    RETURN_TYPES = ("SA_CONNECTION",)
    RETURN_NAMES = ("connection",)
    DESCRIPTION = "Configure once, reuse across nodes. For any relay, override the base URL and choose its API protocol. / 一次配置，多节点共用。中转站填写其地址并选择接口格式。"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "provider": (list(PROVIDERS), {"default": "Custom / 自定义"}),
                "base_url": string(
                    tooltip="Include the API version, e.g. https://host/v1. Leave blank for official presets. / 填含版本号的基础地址；预设平台可留空。"
                ),
                "api_key": string(
                    "env:COMFY_API_KEY",
                    tooltip="Paste a key, env:VARIABLE or key:local_name. Raw pasted keys are saved in workflows. / 可填密钥、env:变量名、key:本地名称。直接填写会保存在工作流中。",
                ),
                "protocol": (
                    PROTOCOLS,
                    {
                        "default": "auto",
                        "tooltip": "auto follows the provider; relays can use any of these protocols. / auto 跟随平台；中转站按其文档选择。",
                    },
                ),
            }
        }

    def build(self, provider, base_url, api_key, protocol="auto"):
        return (connection(provider, base_url, api_key, protocol),)


class APIOptions:
    CATEGORY = CATEGORY + "/Advanced"
    FUNCTION = "build"
    RETURN_TYPES = ("SA_OPTIONS",)
    RETURN_NAMES = ("options",)
    DESCRIPTION = "Optional settings. Connect only when needed. Extra JSON overrides defaults and merges nested objects. / 按需连接。额外 JSON 可覆盖默认参数，嵌套对象会合并。"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "system_prompt": string(multiline=True),
                "timeout": ("INT", {"default": 180, "min": 1, "max": 3600}),
                "endpoint": string(
                    tooltip="Optional endpoint override, relative to base URL. / 可选，覆盖接口路径。"
                ),
                "extra_body": string(
                    "{}",
                    True,
                    "Provider-specific parameters, e.g. temperature, max_tokens, quality. / 平台额外参数。",
                ),
                "headers": string(
                    "{}",
                    True,
                    "Optional custom headers; env: and key: references supported. / 可选请求头，支持密钥引用。",
                ),
                "image_api": (
                    ["auto", "images", "chat", "responses"],
                    {
                        "default": "auto",
                        "tooltip": "Image nodes only. Gemini always uses its native API. / 仅图像节点；Gemini 使用原生接口。",
                    },
                ),
                "image_field": (
                    ["auto", "image", "image[]"],
                    {
                        "default": "auto",
                        "tooltip": "Multipart field expected by your relay. / 中转站要求的图片表单字段。",
                    },
                ),
            }
        }

    def build(
        self,
        system_prompt,
        timeout,
        endpoint,
        extra_body,
        headers,
        image_api,
        image_field,
    ):
        return (
            {
                "system_prompt": system_prompt,
                "timeout": timeout,
                "endpoint": endpoint.strip(),
                "extra_body": json_object(extra_body, "Extra body / 额外参数"),
                "headers": json_object(headers, "Headers / 请求头"),
                "image_api": image_api,
                "image_field": image_field,
            },
        )


class APIText:
    CATEGORY = CATEGORY
    FUNCTION = "execute"
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("text", "response_json")
    DESCRIPTION = "Text in, text out. Supports OpenAI-compatible, Responses, Gemini and Claude APIs. / 输入文本，输出文本。支持四种接口格式。"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "connection": ("SA_CONNECTION",),
                "model": MODEL,
                "prompt": PROMPT,
                "run_id": RUN_ID,
            },
            "optional": {"options": ("SA_OPTIONS",)},
        }

    def execute(self, connection, model, prompt, run_id=0, options=None):
        return request_text(connection, model, prompt, options=options)


class APIVision(APIText):
    DESCRIPTION = "Ask about one or more images. Image order follows inputs 1–4, then the image set. / 输入一张或多张图进行识别、描述、比较。顺序为 1–4，再加图像集合。"

    @classmethod
    def INPUT_TYPES(cls):
        schema = super().INPUT_TYPES()
        schema["required"]["image_1"] = ("IMAGE",)
        schema["optional"].update(IMAGE_PORTS)
        return schema

    def execute(
        self,
        connection,
        model,
        prompt,
        image_1,
        run_id=0,
        options=None,
        image_2=None,
        image_3=None,
        image_4=None,
        image_set=None,
    ):
        return request_text(
            connection,
            model,
            prompt,
            collect_images(image_1, image_2, image_3, image_4, image_set),
            options,
        )


class APIImage:
    CATEGORY = CATEGORY
    FUNCTION = "execute"
    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("images", "text", "response_json")
    OUTPUT_IS_LIST = (True, False, False)
    DESCRIPTION = "Generate images. Connect images to Preview Image or Save Image. Supports Images, Gemini, chat and Responses image APIs. / 生成图像，输出连接预览或保存图像。"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "connection": ("SA_CONNECTION",),
                "model": MODEL,
                "prompt": PROMPT,
                "size": string(
                    "auto",
                    tooltip="Images API: 1024x1024 etc. Gemini/chat: auto or aspect ratio, e.g. 16:9. / Images 接口填像素尺寸；Gemini/chat 可填比例。",
                ),
                "count": ("INT", {"default": 1, "min": 1, "max": 16}),
                "run_id": RUN_ID,
            },
            "optional": {"options": ("SA_OPTIONS",)},
        }

    def execute(
        self, connection, model, prompt, size="auto", count=1, run_id=0, options=None
    ):
        return request_images(connection, model, prompt, size, count, options=options)


class APIImageEdit(APIImage):
    DESCRIPTION = "Edit with one or many reference images. Connect up to four inputs or chain Image Set nodes for more. White mask areas are edited. / 支持单图、多图编辑。可直接接四张或用图像集合扩展。遮罩白色区域为编辑区。"

    @classmethod
    def INPUT_TYPES(cls):
        schema = super().INPUT_TYPES()
        schema["required"]["image_1"] = ("IMAGE",)
        schema["optional"].update({**IMAGE_PORTS, "mask": ("MASK",)})
        return schema

    def execute(
        self,
        connection,
        model,
        prompt,
        image_1,
        size="auto",
        count=1,
        run_id=0,
        options=None,
        image_2=None,
        image_3=None,
        image_4=None,
        image_set=None,
        mask=None,
    ):
        images = collect_images(image_1, image_2, image_3, image_4, image_set)
        return request_images(
            connection, model, prompt, size, count, images, mask, options
        )


class APIImages:
    CATEGORY = CATEGORY
    FUNCTION = "collect"
    RETURN_TYPES = ("SA_IMAGES", "INT")
    RETURN_NAMES = ("image_set", "count")
    DESCRIPTION = "Combine references without resizing. Chain image_set to collect more. / 原尺寸收集多张图；串接图像集合可继续添加。"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image_1": ("IMAGE",)}, "optional": dict(IMAGE_PORTS)}

    def collect(
        self, image_1, image_2=None, image_3=None, image_4=None, image_set=None
    ):
        images = collect_images(image_set, image_1, image_2, image_3, image_4)
        return images, len(images)


class APIRequest:
    CATEGORY = CATEGORY + "/Advanced"
    FUNCTION = "execute"
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("result", "response_json")
    DESCRIPTION = "Custom synchronous JSON APIs. Templates: {{prompt}}, {{model}}, {{images}}, {{images_base64}}. Result path uses JSON Pointer. / 自定义同步 JSON 接口。支持提示词、模型、多图模板及结果路径。异步任务请按平台文档另行查询。"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "connection": ("SA_CONNECTION",),
                "method": (["POST", "GET"],),
                "endpoint": string("chat/completions"),
                "model": MODEL,
                "prompt": PROMPT,
                "body_json": string(
                    '{"model":"{{model}}","messages":[{"role":"user","content":"{{prompt}}"}]}',
                    True,
                ),
                "result_path": string(
                    "/choices/0/message/content",
                    tooltip="Empty = entire JSON; e.g. /data/0/url. / 留空输出全部 JSON。",
                ),
                "run_id": RUN_ID,
            },
            "optional": {"image_set": ("SA_IMAGES",), "options": ("SA_OPTIONS",)},
        }

    def execute(
        self,
        connection,
        method,
        endpoint,
        model,
        prompt,
        body_json,
        result_path="",
        run_id=0,
        image_set=None,
        options=None,
    ):
        options = options or {}
        body = template_body(
            json_object(body_json), prompt, model, collect_images(image_set)
        )
        body = merge(body, options.get("extra_body", {}))
        if body.get("stream"):
            raise APIError("请设 stream=false / Use stream=false.")
        response, secrets = request_json(
            connection,
            endpoint,
            body,
            headers=options.get("headers"),
            timeout=options.get("timeout", 180),
            method=method,
        )
        result = select_path(response, result_path.strip())
        return (
            dump_response(result, secrets)
            if not isinstance(result, str)
            else redact(result, secrets),
            dump_response(response, secrets),
        )


class APIImageDecode:
    CATEGORY = CATEGORY + "/Advanced"
    FUNCTION = "execute"
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    DESCRIPTION = "Decode an image URL, data URL or base64 returned by a custom API. / 把通用请求得到的图片地址或 base64 转为图像。"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image_data": string(multiline=True)}}

    def execute(self, image_data):
        return (decode_image(image_data.strip()),)


class APIShowText:
    CATEGORY = CATEGORY
    FUNCTION = "show"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    OUTPUT_NODE = True
    DESCRIPTION = "Display text directly on this node. / 直接在节点上显示文本结果。"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"text": ("STRING", {"forceInput": True})}}

    def show(self, text):
        return {"ui": {"text": [text]}, "result": (text,)}


NODE_CLASS_MAPPINGS = {
    "SAConnection": APIConnection,
    "SAText": APIText,
    "SAVision": APIVision,
    "SAImage": APIImage,
    "SAImageEdit": APIImageEdit,
    "SAImages": APIImages,
    "SAOptions": APIOptions,
    "SARequest": APIRequest,
    "SAImageDecode": APIImageDecode,
    "SAShowText": APIShowText,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "SAConnection": "API Connection",
    "SAText": "API Text",
    "SAVision": "API Vision",
    "SAImage": "API Generate Image",
    "SAImageEdit": "API Edit Images",
    "SAImages": "API Image Set",
    "SAOptions": "API Options",
    "SARequest": "API Custom Request",
    "SAImageDecode": "API Decode Image",
    "SAShowText": "API Show Text",
}
