# DESIGN_SPEC.md

## Overview

Summarix 是一个面向 Chrome/Edge 的浏览器插件和 FastAPI 后端。插件在 Side Panel 中提供弱打扰登录、网页对话、新建聊天、下一步建议问题、历史记录和模型设置，内容脚本使用 Readability.js 提取网页正文，后台脚本使用 `chrome.tabs.captureVisibleTab` 生成截图。

后端使用 Cookie + JWT 完成用户认证，采用 access/refresh 双 Cookie。业务数据存储在 PostgreSQL 中，用户可见的会话历史由业务表维护，ADK 的 session 和 artifact 能力用于 AI 运行时。截图先通过独立 artifact 接口上传到 `FileArtifactService`，聊天流只引用 artifact id。插件还提供基于网页正文的快捷改写能力，可将主体文章转换为小红书文案或短视频脚本。

AI 对话通过 POST SSE 返回，前端用 fetch 解析 `text/event-stream`，实现动态打字机效果。模型通过 LiteLLM 接入，默认模型为 `qwen3.5-flash`，文本总结、通用对话、小红书文案、短视频脚本和下一步建议问题可以分别配置；每个角色独立支持 thinking mode 的默认、开启、关闭三态。截图和图片会交给当前任务模型处理，聊天界面会提醒用户选择支持图像输入的模型。

## Example Use Cases

1. 用户注册并登录插件后，打开新闻网页，点击正文提取，再输入“总结这篇文章”。后端返回流式总结，并把用户消息与 AI 回复保存到历史记录。
2. 用户点击截图按钮，插件上传当前可视区域截图，随后输入“结合截图指出页面重点”。后端把 artifact id 与消息一起交给聊天服务处理。
3. 用户在历史页打开旧会话，查看之前的用户问题、AI 回复和上传附件元数据。
4. 用户点击截图按钮后发起图像相关提问，聊天界面提醒当前任务模型需要支持图像输入，后端把截图和文本上下文交给 ADK 智能体团队处理。
5. 用户打开文章页后，点击“小红书文案”或“短视频脚本”，插件提取网页正文并通过流式接口返回改写结果；其中小红书文案应为可直接复制发布的成品，短视频脚本保持结构化输出。
6. AI 回复保存后，插件显示 3 个可点击的下一步问题；用户也可以刷新建议问题并直接点击继续提问。

## Tools Required

- Chrome Extension APIs：Side Panel、content scripts、tabs、captureVisibleTab、storage。
- Readability.js：在内容脚本中提取网页正文。
- FastAPI：提供认证、artifact、SSE 聊天、历史、设置接口。
- PostgreSQL：保存用户、refresh token、会话、消息、附件元数据和模型偏好。
- ADK Python：负责 agent、runner、session 和 artifact 服务。
- LiteLLM：统一接入多模型提供商。

## Constraints & Safety Rules

- 前端页面调用 AI 内容接口一律使用流式接口。
- 写接口必须在 OpenAPI 中提供请求示例。
- ADK 工具 docstring 不出现 `tool_context`。
- 前端只有在后端明确返回认证失效时才清理登录状态；后端不可访问时提示服务暂时不可访问，不丢弃本地用户缓存。
- 首版不做 OAuth、CI/CD、复杂观测、计费、RAG 和正式对象存储。
- 本地无模型 key 时可使用 `CHAT_AGENT_MODE=mock` 跑通接口与插件流程。

## Success Criteria

- 后端可以通过 `uv run --env-file .env main.py` 启动，OpenAPI 和 `/health` 可访问。
- 用户可以注册、登录、刷新会话、退出登录。
- 插件可以提取网页正文、上传截图、发起流式聊天并展示增量回复。
- 插件可以新建聊天，并在 AI 回复后显示可点击的下一步建议问题。
- 插件可以将网页主体文章快捷转换为小红书文案和短视频脚本；其中小红书文案输出可直接复制发布的成品，短视频脚本保持结构化模板。
- 云端历史可列出并查看详情。
- 模型偏好和每个角色的 thinking mode 可读取和更新。
- 认证、artifact、聊天流、历史和设置接口都有正常路径测试。

## Edge Cases to Handle

- access token 过期时，前端尝试使用 refresh cookie 静默恢复。
- 截图文件超过大小限制时，后端返回 413。
- 聊天请求引用的 artifact 不属于当前用户时，不会被加载给模型。
- 会话 id 不存在或不属于当前用户时，后端创建新会话或返回 404。
- 浏览器页面不允许内容脚本访问时，插件向用户显示提取失败信息。
