# Simple API · 简易 API

[English](README.en.md)

在 ComfyUI 中调用模型 API。配置连接、填写模型、输入内容、连接输出。界面随 ComfyUI 切换中文或英文。

**v0.2.0 新增通用“API 自动图像”**：自动上传图片、提交同步或异步请求、轮询任务并下载结果。内置 APIKO 和 OpenAI Images 预设；其他平台连接独立“API 流程配置”，按其文档设置请求格式即可。

**APIKO / Nano Banana 2.1 最简用法：** 多个“加载图像” → **API 自动图像** → 预览图像 / 保存图像。平台选 `APIKO`，填密钥和编辑要求，模型留空自动使用 `nano-banana-2.1`，其余选项保持默认即可；不需要 API 连接节点。可导入 `examples/06-automatic-multi-image-edit.json`。

## 安装

1. 将本项目文件夹放入 `ComfyUI/custom_nodes/comfyui-simple-api`。
2. 用 **ComfyUI 自己的 Python** 安装依赖：`python -m pip install -r requirements.txt`。
3. 重启 ComfyUI，搜索 `Simple API`。

也可在 `ComfyUI/custom_nodes` 中执行：

```sh
git clone https://github.com/playboy-dongan/comfyui-simple-api.git
```

Windows 便携版，在便携版根目录执行：

```powershell
.\python_embeded\python.exe -m pip install -r .\ComfyUI\custom_nodes\comfyui-simple-api\requirements.txt
```

本包复用 ComfyUI 的 PyTorch，不会替换 GPU 环境。

## 先用这三个流程

| 用途 | 连接方式 |
| --- | --- |
| 文本请求 | API 连接 → API 文本 → API 显示文本 |
| 文生图 | API 连接 → API 生成图像 → 预览图像 / 保存图像 |
| 多图编辑 | 多个加载图像 → API 多图编辑 → 预览图像 / 保存图像；同时连接 API 连接 |

可直接导入 [examples](examples) 中的工作流。示例模型名是可替换的填写位置，请使用你所选平台实际提供的模型 ID。

**API 连接只需关注四项：**

| 字段 | 怎么填 |
| --- | --- |
| 平台 | 官方服务选对应平台；中转站选“自定义” |
| API 地址 | 中转站填写它给的基础地址，例如 `https://你的平台/v1`；预设平台留空使用内置地址 |
| API 密钥 | 可直接填；推荐 `key:main` 从本地文件读取 |
| 接口格式 | `auto` 跟随平台；中转站按文档选 `openai`、`responses`、`gemini` 或 `anthropic` |

**模型名填在用途节点上**，可以填写任何平台支持的模型 ID，不受固定列表限制。一个连接可以供不同模型共用。服务端必须支持所选用途，例如文本模型不能生成图像。

## 包含的节点

| 节点 | 用途 |
| --- | --- |
| API 自动图像 | 通用自动上传、同步/异步图像请求、任务轮询、图像下载 |
| API 自动请求 | 使用同一流程返回文本或 JSON 结果 |
| API 流程配置 | 为其他平台设置上传方式、请求体、认证、任务状态、结果路径 |
| API 连接 | 共用地址、密钥和接口格式 |
| API 文本 | 文本 → 文本 |
| API 看图问答 | 一张或多张图 + 文本 → 文本 |
| API 生成图像 | 文本 → 图像 |
| API 多图编辑 | 一张或多张图 + 编辑要求 → 图像，可选遮罩 |
| API 图像集合 | 收集更多参考图，保留各自尺寸 |
| API 显示文本 | 在节点内查看结果 |
| API 高级选项 | 按需连接系统提示词、超时、额外参数、请求头或接口路径 |
| API 通用请求 | 自定义同步 JSON GET / POST 接口 |
| API 解码图像 | 图片 URL、data URL 或 base64 → 图像 |

多图节点可直接连接四个图像输入，每个输入也接受 ComfyUI 图像批次。超过四路时，用“图像集合”串接，输出接到 `image_set`。集合节点先保留已有集合再添加图 1–4；问答和编辑节点按图 1–4、再集合的顺序发送。数量上限由服务商决定。

输出图像以 ComfyUI 图像列表返回，不会强行缩放到同一尺寸，直接连接预览或保存节点即可。编辑遮罩白色表示要修改的区域，尺寸须与第一张图一致。Gemini、chat 和 Responses 图像模式不接受此遮罩输入。

## 平台与兼容范围

| 接口格式 | 文本 / 看图 | 生成 / 编辑图像 |
| --- | --- | --- |
| OpenAI 兼容 | `/chat/completions` | `/images/generations`、multipart `/images/edits` |
| OpenAI Responses | `/responses` | 默认使用 Images API；高级选项可改用 Responses 图像工具 |
| Gemini 原生 | `/models/{模型}:generateContent` | 同一原生接口，支持多图参考 |
| Claude 原生 | `/messages` | Claude 不提供图像生成 |

内置 OpenAI、Gemini、Claude、DeepSeek、百炼、硅基流动、OpenRouter、Ollama 地址预设；都可覆盖地址。百炼默认中国内地区域，其他区域填写对应地址。**预设地址不代表该平台的所有功能都使用同一格式**；部分百炼图像模型、异步任务或专有接口需要通用请求或额外适配。

OpenRouter 预设的图像模式使用 chat multimodal 接口；其他兼容中转站如要求此格式，可连接高级选项，将 `image_api` 设为 `chat`。Responses 图像模式填写支持图像工具的主模型，而不是仅供 Images API 使用的图像模型。

`size=auto` 不发送尺寸约束。Images 模式可填 `1024x1024` 等平台支持的值。Gemini 和 chat 模式可填 `16:9`，像素尺寸会换算成比例；分辨率等要求放入平台专用 JSON。Gemini 和 Responses 图像工具每次请求数量须为 1。

### 常见额外参数

连接“API 高级选项”，在“额外参数”填写平台文档支持的 JSON，例如：

```json
{"temperature": 0.7, "max_tokens": 2048}
```

图像接口示例：`{"quality":"high"}`。Gemini 示例：`{"generationConfig":{"imageConfig":{"imageSize":"2K"}}}`。嵌套对象会合并，已有字段可被覆盖。不同模型支持的参数不同，默认不会额外发送 temperature 等非必需参数。

若中转站要求多图字段 `image` 而非 `image[]`，可在高级选项中切换 `image_field`。

## 本地保存密钥

把 `api_keys.example.json` 复制为 `api_keys.json`，将 `main` 的值改为密钥。节点里填 `key:main`。可增加多个名称；文件已被 Git 忽略，不会随工作流保存。

也可在启动 ComfyUI 前设置环境变量，节点填 `env:COMFY_API_KEY`。本地 Ollama 无需认证时，将密钥字段清空。直接粘贴密钥的方式也支持，但密钥会保存在工作流中，分享前应移除。

## 通用 JSON 接口

模板在解析 JSON 后替换，因此提示词中的引号、换行不会破坏 JSON。`{{images}}` 与 `{{images_base64}}` 必须独占一个 JSON 字符串值，会分别替换成图片 data URL 数组和纯 base64 数组。

```json
{"model":"{{model}}","prompt":"{{prompt}}","images":"{{images}}"}
```

结果路径采用 JSON Pointer，例如 `/data/0/url` 或 `/choices/0/message/content`；留空输出全部响应。返回图片地址或 base64 时，接“API 解码图像”。需要传递大段 base64 时使用结果路径，辅助的响应 JSON 会缩略大字段。GET 将 JSON 对象作为查询参数。

“API 通用请求”节点发送一次同步 JSON 请求，也可分别提交和查询 JSON 任务接口。

需要自动上传或轮询时，改用 **API 自动图像 / API 自动请求**。流程支持 multipart 上传、JSON base64 上传、直接内联图片、自定义 GET/POST 轮询、独立结果获取接口及 JSON Pointer 结果路径。详细配置见 [自动请求说明](docs/AUTOMATIC_REQUESTS.md)。SSE、WebSocket、平台专用签名或多阶段对象存储上传仍需要对应适配。

## 执行与排错

- 相同输入沿用 ComfyUI 缓存；需要再次调用时，更改“重新请求编号”。它只控制缓存，不是模型 seed。
- 没有文本或保存/预览等输出节点的分支不会执行。文本分支接“API 显示文本”。
- 超时默认 180 秒，可在高级选项中调整。请求不自动重试，避免重复计费。
- 401：检查密钥；404：检查基础地址、接口格式和模型；429：检查额度和频率。
- 辅助响应 JSON 会隐藏已知密钥和缩略大字段；图像下载不会附带模型 API 的认证头。
- 不会自动给地址添加 `/v1`，也不接受将完整调用路径当作基础地址；请按服务商文档填写。

## 开发与社区发布

本项目为独立实现，遵循 ComfyUI 官方仍支持的 V1 节点定义和原生 locales 翻译。运行测试：

```sh
python -m pip install pytest
python -m pytest -q
```

已包含 MIT 许可证、版本元数据、双语说明、示例和测试。仓库为 [playboy-dongan/comfyui-simple-api](https://github.com/playboy-dongan/comfyui-simple-api)。Registry / Manager 可安装状态取决于平台审核；也可直接从 Git 仓库安装。维护者发布流程见 [发布说明](docs/PUBLISHING.md)。

接口依据与社区参考见 [sources](docs/SOURCES.md)。测试使用本地模拟服务；真实模型兼容性还取决于服务商、模型权限和具体参数。
