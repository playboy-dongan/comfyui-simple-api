# 发布到 ComfyUI 社区 / Publishing

仓库：[playboy-dongan/comfyui-simple-api](https://github.com/playboy-dongan/comfyui-simple-api)。发布者：`playboy-dongan`。

1. 更新代码和 `pyproject.toml` 的版本号，运行测试并推送到仓库。
2. 使用 Comfy Registry 发布者 `playboy-dongan` 的 Registry 发布密钥。
3. 检查 `pyproject.toml` 的 `PublisherId` 和 `Repository` 与实际身份一致。
4. 使用 Comfy CLI，在本项目根目录运行 `comfy node publish`，按提示提供 **Registry 发布密钥**。
5. 按平台流程完成审核或登记。Registry 为 Manager 提供节点包；可用性以实际平台状态为准。

模型 API 密钥与 Registry 发布密钥是两种不同的凭据。不要提交 `api_keys.json` 或 `.env`。

官方流程：[Publishing Nodes](https://docs.comfy.org/registry/publishing)。本项目没有伪造 Publisher ID 或仓库地址，也没有配置自动发布。

For subsequent releases, update the version, run tests, push the code, then run `comfy node publish` with the publisher's Registry key. Review and Manager availability depend on the platform. Model credentials and publishing credentials are separate.
