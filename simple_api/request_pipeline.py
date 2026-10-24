"""Provider-independent upload → submit → poll → fetch → parse pipeline."""

import base64
import copy
import hashlib
import json
import re
import time
from urllib.parse import quote, urlsplit

from .config import APIError, Connection, resolve_secret
from .images import decode_image, extract_image_values, png_bytes
from .request_profiles import validate_profile
from .transport import dump_response, redact, request_json

TOKEN = re.compile(r"\{\{([a-z_][a-z0-9_]*)\}\}")
OMIT = object()


def render(value, context):
    if isinstance(value, str):
        match = TOKEN.fullmatch(value)
        if match:
            name = match[1]
            if name not in context:
                raise APIError(
                    f"未知模板变量 {name} / Unknown template variable: {name}."
                )
            return copy.deepcopy(context[name]) if context[name] is not None else OMIT

        def replace(match):
            name = match[1]
            if name not in context or context[name] is None:
                raise APIError(
                    f"模板变量 {name} 不可用 / Template variable {name} is unavailable."
                )
            return str(context[name])

        return TOKEN.sub(replace, value)
    if isinstance(value, dict):
        output = {}
        for key, item in value.items():
            rendered = render(item, context)
            if rendered is not OMIT:
                output[key] = rendered
        return output
    if isinstance(value, list):
        output = []
        for item in value:
            rendered = render(item, context)
            if rendered is OMIT:
                continue
            if (
                isinstance(item, str)
                and TOKEN.fullmatch(item)
                and isinstance(rendered, list)
            ):
                output.extend(rendered)
            else:
                output.append(rendered)
        return output
    return value


def select_many(value, path):
    """JSON Pointer with * for every array element or object value."""
    if path == "":
        return [value]
    if not isinstance(path, str) or not path.startswith("/"):
        raise APIError(
            "结果路径需使用 JSON Pointer，如 /data/*/url / Use a JSON Pointer result path."
        )
    current = [value]
    for token in path[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        following = []
        for item in current:
            if token == "*":
                if isinstance(item, list):
                    following.extend(item)
                elif isinstance(item, dict):
                    following.extend(item.values())
            else:
                try:
                    following.append(
                        item[int(token)] if isinstance(item, list) else item[token]
                    )
                except (KeyError, IndexError, TypeError, ValueError):
                    continue
        current = following
    if not current:
        raise APIError(f"结果路径不存在：{path} / Result path not found: {path}.")
    return current


def image_result(response, path, timeout):
    values = []

    def collect(value):
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            values.extend(extract_image_values(value))

    for value in select_many(response, path):
        collect(value)
    if not values:
        raise APIError(
            "结果中没有图像，请检查 result_path / No images found; check result_path."
        )
    return [decode_image(value, timeout()) for value in values]


def check_interrupted():
    try:
        from comfy.model_management import throw_exception_if_processing_interrupted
    except ImportError:
        return
    throw_exception_if_processing_interrupted()


class RequestPipeline:
    def __init__(self, *, clock=None, sleep=None, interrupt=None):
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self.interrupt = interrupt or check_interrupted
        self.pending = None

    def execute(
        self,
        profile,
        api_key,
        model,
        prompt,
        images=(),
        size="auto",
        resolution="auto",
        run_id=0,
        progress=None,
        process_result=None,
    ):
        profile = validate_profile(profile)
        if len(images) > profile["max_images"]:
            raise APIError(
                f"参考图不能超过 {profile['max_images']} 张（含批次） / Too many reference images, including batch frames."
            )
        operation = "edit" if images else "generate"
        if operation not in profile:
            raise APIError(
                f"流程未配置 {operation} 请求 / No {operation} request is configured."
            )
        if not prompt.strip():
            raise APIError("请填写提示词 / Enter a prompt.")
        key = resolve_secret(api_key)
        secrets = {key}
        if not key and profile.get("auth", "bearer") != "none":
            raise APIError("请填写 API 密钥 / Enter your API key.")
        model = model.strip() or profile.get("model", "")
        if not model and "{{model}}" in json.dumps(profile):
            raise APIError("请填写模型名称 / Enter the model ID.")
        context = {
            "api_key": key,
            "model": model,
            "prompt": prompt,
            "task_id": None,
            "size": profile.get("size") if size == "auto" else size,
            "resolution": profile.get("resolution")
            if resolution == "auto"
            else resolution,
            "images": [],
            "image": None,
            "images_base64": [],
            "images_data_urls": [],
            "image_base64": None,
            "image_data_url": None,
            "filename": None,
        }
        deadline = self.clock() + profile["timeout"]
        config = Connection("openai", profile["base_url"], "")

        def remaining():
            self.interrupt()
            seconds = deadline - self.clock()
            if seconds <= 0:
                raise APIError("等待任务超时 / Task wait timed out.")
            return max(1, min(60, seconds))

        def notify(value):
            if progress:
                progress(value)

        def pause(seconds):
            until = min(deadline, self.clock() + seconds)
            while self.clock() < until:
                self.interrupt()
                self.sleep(min(0.25, until - self.clock()))
            remaining()

        def send(spec, ctx, files=None, default_method="POST"):
            body = render(spec.get("body", {}), ctx)
            headers = render(
                {**profile.get("headers", {}), **spec.get("headers", {})}, ctx
            )
            auth = profile.get("auth", "bearer")
            if auth == "bearer":
                headers.setdefault("Authorization", f"Bearer {key}")
            elif auth in ("x-api-key", "x-goog-api-key"):
                headers.setdefault(auth, key)
            endpoint_context = {
                **ctx,
                "task_id": quote(str(ctx["task_id"]), safe="")
                if ctx.get("task_id")
                else None,
            }
            endpoint = render(spec["endpoint"], endpoint_context)
            if spec.get("format", "json") == "multipart":
                body = {
                    name: json.dumps(item, ensure_ascii=False)
                    if isinstance(item, (dict, list, bool))
                    else item
                    for name, item in body.items()
                    if item is not None
                }
            elif body.get("stream"):
                raise APIError(
                    "自动请求使用完整响应，请设 stream=false / Use stream=false for automatic requests."
                )
            try:
                response, request_secrets = request_json(
                    config,
                    endpoint,
                    body,
                    files=files,
                    headers=headers,
                    timeout=remaining(),
                    method=spec.get("method", default_method),
                )
                secrets.update(request_secrets)
                return response
            except APIError as error:
                raise APIError(
                    redact(str(error), secrets), status_code=error.status_code
                ) from None

        encoded = []
        identity = {
            name: profile.get(name)
            for name in (
                "base_url",
                "auth",
                "headers",
                "upload",
                "image_item",
                operation,
            )
        }
        digest = hashlib.sha256(key.encode())
        digest.update(
            json.dumps(
                [
                    identity,
                    model,
                    prompt,
                    context["size"],
                    context["resolution"],
                    run_id,
                ],
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        )
        for index, image in enumerate(images, 1):
            remaining()
            raw = png_bytes(image)
            if len(raw) > profile["max_upload_mb"] * 1024 * 1024:
                raise APIError(
                    f"图像 {index} 编码后超过 {profile['max_upload_mb']} MB，请先缩小图片 / Encoded reference {index} is too large; resize it first."
                )
            encoded.append(raw)
            digest.update(len(raw).to_bytes(8, "big"))
            digest.update(raw)
        fingerprint = digest.hexdigest()
        if self.pending and self.pending["fingerprint"] != fingerprint:
            self.pending = None
        try:
            if not self.pending:
                # Lazy encoding of base64 templates; multipart uploads do not need it.
                all_specs = json.dumps(profile)
                needs_base64 = any(
                    token in all_specs
                    for token in (
                        "{{images_base64}}",
                        "{{image_base64}}",
                        "{{image_data_url}}",
                        "{{images_data_urls}}",
                    )
                )
                if needs_base64 or (
                    not profile.get("upload")
                    and profile[operation].get("format", "json") == "json"
                ):
                    context["images_base64"] = [
                        base64.b64encode(raw).decode("ascii") for raw in encoded
                    ]
                    context["images_data_urls"] = [
                        "data:image/png;base64," + value
                        for value in context["images_base64"]
                    ]
                    context["image_base64"] = next(iter(context["images_base64"]), None)
                    context["image_data_url"] = next(
                        iter(context["images_data_urls"]), None
                    )
                context["images"] = context["images_data_urls"]
                upload = profile.get("upload")
                if upload and images:
                    urls = []
                    for index, raw in enumerate(encoded):
                        ctx = {**context, "filename": f"reference_{index + 1}.png"}
                        if needs_base64:
                            ctx.update(
                                image_base64=context["images_base64"][index],
                                image_data_url=context["images_data_urls"][index],
                                image=context["images_data_urls"][index],
                            )
                        files = (
                            [
                                (
                                    upload.get("file_field", "file"),
                                    (ctx["filename"], raw, "image/png"),
                                )
                            ]
                            if upload.get("format", "multipart") == "multipart"
                            else None
                        )
                        uploaded = send(upload, ctx, files=files)
                        url = select_many(uploaded, upload.get("url_path", "/url"))[0]
                        try:
                            parts = urlsplit(url) if isinstance(url, str) else None
                        except ValueError:
                            parts = None
                        if (
                            not parts
                            or parts.scheme
                            not in (
                                ("https",)
                                if upload.get("https_only")
                                else ("http", "https")
                            )
                            or not parts.hostname
                            or parts.username
                            or parts.password
                        ):
                            raise APIError(
                                "上传未返回有效图片链接，请检查 upload.url_path / Upload returned no valid image URL; check upload.url_path."
                            )
                        urls.append(url)
                        notify(round(20 * (index + 1) / len(images)))
                    context["images"] = urls
                context["image"] = next(iter(context["images"]), None)
                if profile.get("image_item") is not None:
                    references = context["images"]
                    context["images"] = [
                        render(
                            profile["image_item"],
                            {
                                **context,
                                "image": reference,
                                "image_base64": context["images_base64"][index]
                                if context["images_base64"]
                                else None,
                                "image_data_url": context["images_data_urls"][index]
                                if context["images_data_urls"]
                                else None,
                                "filename": f"reference_{index + 1}.png",
                            },
                        )
                        for index, reference in enumerate(references)
                    ]
                spec = profile[operation]
                files = None
                if spec.get("format") == "multipart":
                    field = spec.get("file_field", "auto")
                    field = (
                        ("image[]" if len(encoded) > 1 else "image")
                        if field == "auto"
                        else field
                    )
                    files = [
                        (field, (f"reference_{index + 1}.png", raw, "image/png"))
                        for index, raw in enumerate(encoded)
                    ]
                response = send(spec, context, files=files)
                poll = profile.get("poll")
                task_value = (
                    select_many(response, poll["task_id_path"])[0] if poll else ""
                )
                if poll and (
                    isinstance(task_value, bool)
                    or not isinstance(task_value, (str, int))
                ):
                    raise APIError(
                        "接口未返回有效任务 ID，请检查任务记录 / No valid task ID returned; check provider Task Logs."
                    )
                task_id = str(task_value)
                if poll and (not task_id or len(task_id) > 512):
                    raise APIError(
                        "接口未返回有效任务 ID，请检查任务记录 / No valid task ID returned; check provider Task Logs."
                    )
                self.pending = {
                    "fingerprint": fingerprint,
                    "id": task_id,
                    "response": response,
                    "final": response if not poll else None,
                    "secrets": secrets,
                }
            secrets.update(self.pending.get("secrets", ()))
            self.pending["secrets"] = secrets
            context["task_id"] = self.pending["id"]
            poll = profile.get("poll")
            failures = 0
            notify(25)
            while self.pending["final"] is None:
                remaining()
                response = self.pending["response"]
                try:
                    status = str(select_many(response, poll["status_path"])[0])
                except APIError:
                    if self.pending.get("polled"):
                        raise
                    status = None  # Some providers return only an ID on submit.
                if status in [
                    str(value)
                    for value in poll.get("failure_states", ["failed", "cancelled"])
                ]:
                    task_id = self.pending["id"]
                    self.pending = None
                    try:
                        reason = select_many(
                            response, poll.get("error_path", "/error")
                        )[0]
                    except APIError:
                        reason = response
                    raise APIError(
                        f"任务失败 / Task failed ({task_id}): {dump_response(reason, secrets)}"
                    )
                if status in [
                    str(value) for value in poll.get("success_states", ["completed"])
                ]:
                    self.pending["final"] = (
                        send(profile["result_request"], context, default_method="GET")
                        if profile.get("result_request")
                        else response
                    )
                    break
                if (
                    status is not None
                    and poll.get("pending_states")
                    and status not in [str(value) for value in poll["pending_states"]]
                ):
                    raise APIError(
                        "未知任务状态，请检查状态配置 / Unknown task status; check the profile."
                    )
                pause(poll.get("interval", 5))
                try:
                    response = send(poll, context, default_method="GET")
                    self.pending.update(response=response, polled=True)
                    failures = 0
                except APIError as error:
                    code = error.status_code
                    failures += 1
                    if failures >= 5 or (
                        code is not None and code not in (408, 425, 429) and code < 500
                    ):
                        raise
                    pause(min(30, poll.get("interval", 5) * 2 ** (failures - 1)))
            notify(95)
            response, task_id = self.pending["final"], self.pending["id"]
            result = (
                process_result(response, profile["result_path"], remaining)
                if process_result
                else response
            )
            if isinstance(result, str):
                result = redact(result, secrets)
            remaining()
            raw = dump_response(response, secrets)
            self.pending = None
            notify(100)
            return result, task_id, raw
        except APIError as error:
            if self.pending:
                identifier = self.pending["id"] or "synchronous result / 同步结果"
                raise APIError(
                    f"{redact(str(error), secrets)}\nTask: {identifier}\n保持输入和重新请求编号不变，再次执行可继续取回结果；重启后请查看平台任务记录 / Re-run unchanged inputs to resume; after restart, check provider Task Logs.",
                    status_code=error.status_code,
                ) from None
            raise
