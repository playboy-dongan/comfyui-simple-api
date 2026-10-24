# 自动请求 / Automatic requests

`API 自动图像` 和 `API 自动请求` 共用同一套通用执行器。平台预设保存在 `simple_api/request_profiles.py`，请求流程通过数据配置。

## 常用操作

- **APIKO Nano Banana 2.1：** 选择 APIKO，填密钥和编辑要求，模型留空。多张图接 image_1–4；更多图用“API 图像集合”。总计最多 14 张。无参考图时自动文生图。有参考图时自动逐张上传并编辑，不需要自行准备链接或查询任务。
- **OpenAI Images：** 选择 OpenAI Images，填写密钥、图像模型和提示词。无图使用 JSON 生成接口；有图使用 multipart 编辑接口。
- **其他平台：** 选择 Custom，连接“API 流程配置”。主节点继续只负责密钥、模型、提示词和图片；平台差异放在配置节点。连接配置后优先使用该配置。
- `size=auto` 不强制比例或像素尺寸；其他值按平台要求填写。`resolution=auto` 使用预设默认值，APIKO 默认为 `1k`。分辨率档位由服务商计费。
- 相同输入使用 ComfyUI 缓存；修改“重新请求编号”可新建一次生成请求。

APIKO 的每张上传图片必须不超过 10 MB。节点按 PNG 编码并在上传前检查所有图片，保留原尺寸，超过限制请先缩小。参考图经服务商上传接口发送到该平台，APIKO 上传链接保留 72 小时，结果链接保留 24 小时。连接原生“保存图像”节点可保存输出。

## 一个不同格式的平台配置示例

在“API 流程配置”填写服务商的基础地址与以下 JSON，并将 `profile` 输出接到自动请求节点。字段路径和状态值必须按该平台的文档修改。

```json
{
  "auth": "x-api-key",
  "model": "YOUR_DEFAULT_MODEL",
  "max_images": 8,
  "max_upload_mb": 20,
  "upload": {
    "endpoint": "media",
    "format": "multipart",
    "file_field": "attachment",
    "url_path": "/data/file/url"
  },
  "edit": {
    "endpoint": "jobs",
    "method": "POST",
    "body": {
      "model_id": "{{model}}",
      "input": {
        "text": "{{prompt}}",
        "references": "{{images}}"
      }
    }
  },
  "poll": {
    "endpoint": "job-status",
    "method": "POST",
    "body": {"job": "{{task_id}}"},
    "task_id_path": "/payload/job_id",
    "status_path": "/data/state",
    "success_states": [2],
    "failure_states": [-1],
    "error_path": "/data/reason",
    "interval": 5
  },
  "result_request": {
    "endpoint": "results/{{task_id}}",
    "method": "GET"
  },
  "result_path": "/payload/images/*/url"
}
```

此示例自动执行：逐张上传 → JSON 提交编辑 → POST 查询数字状态 → GET 获取最终结果 → 下载图片。它不依赖 APIKO 的字段或状态格式。

## 配置规则

| 字段 | 用途 |
| --- | --- |
| `auth` | `bearer`、`x-api-key`、`x-goog-api-key` 或 `none`，默认 bearer |
| `headers` | 额外请求头；自定义认证可设 auth=none 并使用 `{{api_key}}` |
| `model`、`size`、`resolution` | 主节点留空或选择 auto 时的默认值 |
| `upload` | 可省略。配置后，每张图片上传一次；可用 multipart 或 JSON/base64 |
| `image_item` | 可省略。将每张图片映射成接口需要的 JSON 对象，如 inlineData 或 image_url |
| `generate`、`edit` | 无图片、有图片时各自使用的请求。至少配置所需的用途 |
| `poll` | 可省略。配置后根据 task_id_path 获取任务 ID，自动查询状态 |
| `result_request` | 可省略。任务完成后另取最终结果，默认 GET |
| `result_path` | 从最终响应中取出结果的 JSON Pointer，空字符串表示整个响应 |
| `max_images`、`max_upload_mb` | 图片数量与每张 PNG 大小上限；默认 64 张、20 MB |

请求段支持 `endpoint`、`method`、`format`、`headers`、`body`。请求路径相对于基础地址，同源完整地址也可使用。method 支持 GET/POST/PUT/PATCH；GET 的 body 作为查询参数。format 支持 json 和 multipart；multipart 的 file_field 指定图片文件字段名，`auto` 为单图 image、多图 image[]。静态参数直接放 body。

省略 `upload` 可直接提交图片：JSON 使用 base64/data URL 模板，或 edit.format=multipart 直接附加图片文件。JSON 上传示例：

```json
{
  "upload": {
    "endpoint": "upload-base64",
    "format": "json",
    "body": {"content": "{{image_base64}}", "filename": "{{filename}}"},
    "url_path": "/asset/url"
  }
}
```

此片段需合并到完整配置中。同步接口删除 poll；返回图像 base64 时可将 result_path 指向相应字段。一个结果路径可返回单值、数组或包含标准 url / b64_json 字段的对象。

## 模板与结果路径

| 模板 | 内容 |
| --- | --- |
| `{{model}}`、`{{prompt}}`、`{{api_key}}` | 模型、提示词、解析后的密钥 |
| `{{images}}`、`{{image}}` | 上传后的链接数组 / 第一张链接；没有上传步骤时为 data URL |
| `{{images_base64}}`、`{{image_base64}}` | 纯 base64 数组 / 当前图或第一张图 |
| `{{images_data_urls}}`、`{{image_data_url}}` | data URL 数组 / 当前图或第一张图 |
| `{{filename}}` | 上传步骤中的当前文件名 |
| `{{task_id}}` | 创建请求返回的任务 ID，用于查询或结果获取 |
| `{{size}}`、`{{resolution}}` | 尺寸、分辨率；auto 且无预设值时省略对应字段 |

数组或对象模板需独占一个 JSON 字符串值；替换发生在解析 JSON 后，引号或换行不会破坏请求。路径使用 JSON Pointer：`/data/id`、`/output/0/url`；`*` 表示全部数组元素或对象值，例如 `/output/*/url`。

数组模板放在数组内部会展开，可用来组合文本和多个图像对象。例如 `image_item` 配置为 `{"inlineData":{"mimeType":"image/png","data":"{{image_base64}}"}}`，请求体使用 `{"parts":[{"text":"{{prompt}}"},"{{images}}"]}`，即可得到一个文本对象加多张图像对象；image_item 中的 image、image_base64 和 image_data_url 分别代表当前图片。

poll 中的 task_id_path 相对于提交响应，status_path / error_path 相对于轮询响应。状态值可以是文字、数字或布尔值。success_states 默认 completed，failure_states 默认 failed/cancelled；pending_states 可指定允许继续等待的状态。默认 5 秒查询一次，可配置 1–60 秒。任务刚提交只返回 ID 时，也会继续查询。

## 中断、错误与恢复

总等待时间默认 900 秒，可在“API 流程配置”调整为 1–3600 秒。上传和生成提交不会自动重试。轮询遇到临时网络错误、429 或服务端错误时会有限次数重试。任务失败后显示平台原因并停止。

任务已提交后若超时或下载失败，错误信息会显示任务 ID。在同一 ComfyUI 会话、节点实例仍保留的情况下，保持模型、提示词、图片和重新请求编号不变再次执行，会继续查询或下载已有任务，不重新提交生成。修改结果路径或等待时间也可继续恢复。重启后请通过平台任务记录或已有通用请求节点查询该 ID。

API 密钥不会附带到输出图片的下载请求；辅助响应 JSON 会隐藏已知密钥。直接填写密钥会存入工作流，分享前请改用 `key:本地名称` 或 `env:变量名`。

## English quick guide

API Automatic Image handles upload → submit → poll → optional result fetch → decode. API Automatic Request uses the same runner and returns selected text/JSON. APIKO and OpenAI Images are declarative presets; connect API Request Profile for another provider.

For APIKO, select APIKO, enter the key and prompt, and connect references. Leave model blank for nano-banana-2.1. All uploads and polling are automatic. The example `06-automatic-multi-image-edit.json` is ready to connect to Preview/Save Image.

Custom profiles configure authentication, upload format and URL extraction, sync or async JSON/multipart requests, GET/POST polling, arbitrary terminal states, optional separate result retrieval, and JSON Pointer output paths with `*` wildcards. Omit upload for inline base64/data URLs or direct multipart editing. Omit poll for synchronous APIs. The JSON example above demonstrates a different vendor contract with a nested upload URL, numeric states, POST polling and a separate result endpoint.

The default total deadline is 900 seconds. Upload/submission are not automatically retried; transient polling errors have bounded retries. Accepted jobs remain on the node instance until output parsing and image download succeed. Re-running unchanged inputs in the same session resumes that job. Changing run_id deliberately requests a new generation; after a restart, retrieve the task via provider logs or its task ID.
