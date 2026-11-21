# aha-paper API 接入说明

参照用户指定的 ahaexplain `docs/custom-models.md`，以及 `src/daemon/openrouter-media.ts`、
`model-endpoint-settings.ts`、`provider-model-discovery.ts` 的接入约定，独立实现本项目需要的接口。

- 语言：OpenAI Chat Completions 兼容端点，Base URL 为 API 根地址；模型 ID 原样发送。
- Pi 代码模型：协议显式选择 `openai-completions` 或 `anthropic-messages`，与图片协议同一套规则。
  协议是模型定义上的属性，不从模型 ID、也不从"哪个 Key 存在"推断。
  留空 Base URL 继承语言连接及其凭据；指向其他主机时必须单独配置凭据，Key 不跨主机发送。
- OpenRouter Images：`POST /images`，模型目录 `GET /images/models`。
- OpenAI Images 兼容：`POST /images/generations`，目录如服务支持则为 `GET /models`。
- 图片可以继承语言服务的地址与凭据，也可以配置独立图片地址和 Key。
- 模型用途与图片协议显式选择；不能仅凭模型名称推断协议。
- 读取模型目录不生成内容、不改当前模型；无目录的兼容服务仍允许手动填写准确 ID。
- 指定模型不可用时明确报错，不静默切换其他模型、供应商或凭据。
- Key 只保存在本机 `.env`，不写入模型定义、不回传设置响应、不进入互动导出包。
- 配置在任务运行中锁定，避免中途混用服务或模型。
- Edge TTS 继续独立运行，不通过语言/图片 API 合成音频。

支持的环境变量：
`OPENROUTER_API_KEY`（兼容 `OPENAI_API_KEY`）、`OPENAI_BASE_URL`、`OPENAI_MODEL`、
`OPENROUTER_MODEL_CODE`、`OPENROUTER_MODEL_COVER`、`IMAGE_BASE_URL`、`IMAGE_API_KEY`、`IMAGE_PROTOCOL`、
`CODE_PROTOCOL`、`CODE_BASE_URL`、`CODE_API_KEY`。

`IMAGE_PROTOCOL` 可取 `openrouter-images`（默认）或 `openai-images`。
`CODE_PROTOCOL` 可取 `openai-completions`（默认）或 `anthropic-messages`；
取值无法识别时直接报错，不回退到另一个协议。凭据只经 `CODE_MODEL_API_KEY` 传给 Pi 子进程，
运行环境里其他厂商的凭据会被剥离，不会顶替配置的 Key。
Google 原生、Responses、视频生成与3D协议不属于当前实现，不会混用其端点。
