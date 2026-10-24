# 接口依据与社区参考 / Sources

实现使用官方接口定义；社区项目仅用于了解节点组织方式，未复制其实现。

- [ComfyUI custom node properties](https://docs.comfy.org/custom-nodes/backend/server_overview): V1 input/output declarations and execution caching.
- [ComfyUI i18n](https://docs.comfy.org/custom-nodes/i18n): `locales/en/nodeDefs.json` and `locales/zh/nodeDefs.json`.
- [ComfyUI images and masks](https://docs.comfy.org/custom-nodes/backend/images_and_masks): IMAGE tensor and MASK conventions.
- [OpenAI Images edit](https://developers.openai.com/api/reference/resources/images/methods/edit): image multipart requests and masks.
- [OpenAI images and vision](https://developers.openai.com/api/docs/guides/images-vision): image content in Chat Completions and Responses.
- [Gemini image generation](https://ai.google.dev/gemini-api/docs/image-generation): native multimodal `generateContent` and inline image responses.
- [Gemini generateContent reference](https://ai.google.dev/api/generate-content).
- [Anthropic Messages](https://docs.anthropic.com/en/api/messages): native Messages requests and image content.
- [DeepSeek API](https://api-docs.deepseek.com): provider endpoint and compatibility.
- [Qwen / Model Studio endpoints](https://help.aliyun.com/en/model-studio/base-url): regional base URLs.
- [SiliconFlow quickstart](https://docs.siliconflow.cn/docs/userguide/quickstart): compatible endpoint.
- [OpenRouter image generation](https://openrouter.ai/docs/features/multimodal/image-generation): chat multimodal image requests.
- [Ollama OpenAI compatibility](https://docs.ollama.com/openai): local compatible endpoint.
- [APIKO Nano Banana 2.1](https://apiko.app/docs/api-manual/image-series/nano-banana-2.1/images): JSON edit requests and async task contract.
- [APIKO uploads](https://apiko.app/docs/assets): multipart file upload and reference URL requirements.
- [APIKO tasks](https://apiko.app/docs/tasks): polling states and final image URLs.
- [ComfyUI built-in OpenAI nodes](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_api_nodes/nodes_openai.py): community conventions for prompt, reference image and mask ports.
- [ComfyUI Custom API community package](https://github.com/Einzieg/ComfyUI-custom-api): reference for existing community scope; this package is an independent implementation.

API features and supported model parameters evolve. This package does not assert compatibility with every endpoint or every model behind a provider.
