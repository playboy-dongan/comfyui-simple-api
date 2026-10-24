# Simple API

[简体中文](README.md)

Simple ComfyUI nodes for model APIs: connect once, enter a model ID, provide text or images, and use the output. Labels follow ComfyUI's English/Chinese language setting.

## Install

Place this folder at `ComfyUI/custom_nodes/comfyui-simple-api`, install `requirements.txt` with **ComfyUI's Python**, and restart ComfyUI. Search for `Simple API`. The package uses ComfyUI's existing PyTorch installation.

Or clone from `https://github.com/playboy-dongan/comfyui-simple-api.git` into `ComfyUI/custom_nodes`.

Windows portable, from the portable folder:

```powershell
.\python_embeded\python.exe -m pip install -r .\ComfyUI\custom_nodes\comfyui-simple-api\requirements.txt
```

## Start here

| Task | Workflow |
| --- | --- |
| Text | API Connection → API Text → API Show Text |
| Generate images | API Connection → API Generate Image → Preview Image / Save Image |
| Edit multiple images | Load Image nodes + API Connection → API Edit Images → Preview Image / Save Image |

Import the workflows in [examples](examples). Replace their model placeholders with a model ID from your provider.

On **API Connection**, choose a provider, enter your base URL and key, and leave protocol on `auto`. For a relay, choose Custom, provide its versioned base URL (such as `https://host/v1`), and select its documented protocol. Preset URLs can all be overridden. The Qwen preset uses mainland China's endpoint; override it for other regions. URLs are not automatically given a `/v1` suffix. Use a base URL, not a full operation URL.

Enter the model on each task node so one connection can serve different models. Model IDs are free text. Availability and capabilities depend on the provider.

## Nodes

| Node | Purpose |
| --- | --- |
| API Connection | Shared credentials, base URL and protocol |
| API Text | Text → text |
| API Vision | Text + one or more images → text |
| API Generate Image | Text → images |
| API Edit Images | Text + references → images; optional mask |
| API Image Set | Collect references without resizing |
| API Show Text | Display text inside the node |
| API Options | Optional system prompt, timeout, extra JSON, headers and endpoint |
| API Custom Request | Custom synchronous GET/POST JSON APIs |
| API Decode Image | URL, data URL or base64 → image |

Image inputs accept batches. Connect up to four image sources directly, or chain Image Set nodes for more. Image Set keeps its existing set first, then appends inputs 1–4. Vision and Edit send direct inputs 1–4 before their optional set. Provider limits still apply. Output is a list of IMAGE tensors, so images with different dimensions work with Preview Image / Save Image.

White mask areas are edited. The mask must contain one frame matching the first reference image. Only the Images multipart API supports the mask port.

## Compatibility

| Protocol | Text / vision | Image generation / editing |
| --- | --- | --- |
| OpenAI compatible | `/chat/completions` | `/images/generations`, multipart `/images/edits` |
| Responses | `/responses` | Images API by default; optional Responses image tool |
| Gemini | Native `generateContent` | Native multimodal generation and editing |
| Claude | Native `/messages` | Not supported by Claude |

Presets: OpenAI, Gemini, Claude, DeepSeek, Qwen, SiliconFlow, OpenRouter and Ollama. A preset is a connection convenience, not a guarantee that every provider feature uses a standard API. Some Qwen image models and proprietary APIs require Custom Request or further adapters.

OpenRouter defaults to chat image output. Use API Options → `image_api=chat` for other relays with that format, or `responses` for the Responses image tool. For the latter, enter a main model supporting image tools rather than an Images-only model.

`size=auto` sends no size restriction. Images mode accepts provider pixel sizes such as `1024x1024`. Gemini/chat accept aspect ratios such as `16:9`; pixel sizes are converted to ratios. Supply provider-specific resolution settings through extra JSON. Gemini and Responses image tools require count 1.

Connect API Options only when needed. Extra JSON recursively merges with the generated body and can override fields. Examples: `{"temperature":0.7,"max_tokens":2048}`, `{"quality":"high"}`, or for Gemini `{"generationConfig":{"imageConfig":{"imageSize":"2K"}}}`. Only use parameters your model supports. Configure `image_field` when a relay expects repeated `image` rather than `image[]`.

## Keys

Copy `api_keys.example.json` to `api_keys.json`, replace the `main` value, and enter `key:main` in the node. This local file is Git-ignored and is not embedded in workflows. Or set an environment variable before launching ComfyUI and use `env:COMFY_API_KEY`. Leave the field empty for unauthenticated local servers. Pasted keys work but are saved in workflows.

## Custom JSON requests

Templates support `{{prompt}}`, `{{model}}`, `{{images}}` and `{{images_base64}}`. Image placeholders must occupy an entire JSON string value and expand into arrays. Substitution happens after JSON parsing, preserving quotes and newlines in prompts.

```json
{"model":"{{model}}","prompt":"{{prompt}}","images":"{{images}}"}
```

Select a result with a JSON Pointer such as `/data/0/url`, or leave it blank for the entire response. Connect image URL/base64 results to API Decode Image. Select the image value explicitly for large base64 responses; the auxiliary response JSON abbreviates large fields. GET sends the body object as query parameters.

This node performs one synchronous JSON request. Dedicated multipart uploads, SSE, WebSockets, video downloads and automatic polling of async tasks are not implemented. You can submit and separately query JSON job APIs.

## Execution and development

Identical inputs use ComfyUI caching. Change `run_id` to request again; this is not a model seed. Text branches must connect to API Show Text or another output node. Timeout defaults to 180 seconds. No automatic retries. Response JSON redacts known credentials and abbreviates large fields. API credentials are not attached to image downloads.

Run `python -m pip install pytest` and `python -m pytest -q` in an environment with ComfyUI dependencies. Tests use local mock APIs; live provider access and parameter compatibility require provider credentials.

This independent implementation uses ComfyUI's supported V1 node schema and native locales. It includes MIT licensing and package metadata. Repository: [playboy-dongan/comfyui-simple-api](https://github.com/playboy-dongan/comfyui-simple-api). Registry/Manager installability depends on platform review; direct Git installation is available. See [publishing](docs/PUBLISHING.md) and [sources](docs/SOURCES.md).
