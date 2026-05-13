事件¶
Supported in ADKPython v0.1.0TypeScript v0.2.0Go v0.1.0Java v0.1.0
事件是智能体开发工具包（ADK）中信息流的基本单位。它们代表了智能体交互生命周期中每一个重要的发生，从初始用户输入到最终响应以及其间的所有步骤。理解事件至关重要，因为它们是组件通信、状态管理和控制流导向的主要方式。

什么是事件及其重要性¶
ADK 中的 Event 是一个不可变记录，代表智能体执行中的一个特定点。它捕获用户消息、智能体回复、使用工具的请求（函数调用）、工具结果、状态更改、控制信号和错误。



从技术上讲,它是 google.adk.events.Event 类的一个实例,它在基本的 LlmResponse 结构之上构建,通过添加必要的 ADK 特定元数据和 actions 有效载荷。


# 事件的概念结构 (Python)
# from google.adk.events import Event, EventActions
# from google.genai import types

# class Event(LlmResponse): # 简化视图
#     # --- LlmResponse 字段 ---
#     content: Optional[types.Content]
#     partial: Optional[bool]
#     # ... 其他响应字段 ...

#     # --- ADK 特定添加 ---
#     author: str          # 'user' 或智能体名称
#     invocation_id: str   # 整个交互运行的 ID
#     id: str              # 此特定事件的唯一 ID
#     timestamp: float     # 创建时间
#     actions: EventActions # 对副作用和控制很重要
#     branch: Optional[str] # 层次结构路径
#     # ...

事件是 ADK 操作的核心，有几个关键原因：

通信： 它们作为用户界面、Runner、智能体、LLM 和工具之间的标准消息格式。一切都作为 Event 流动。

发出状态和制品更改信号： 事件携带状态修改指令并跟踪制品更新。SessionService 使用这些信号来确保持久性。在 Python 中，更改通过 event.actions.state_delta 和 event.actions.artifact_delta 发出信号。

控制流： 像 event.actions.transfer_to_agent 或 event.actions.escalate 这样的特定字段充当指导框架的信号，决定下一个运行哪个智能体或循环是否应终止。

历史和可观察性： 记录在 session.events 中的事件序列提供了交互的完整、按时间顺序的历史，对于调试、审计和逐步理解智能体行为非常宝贵。

本质上，从用户的查询到智能体的最终答案的整个过程，都是通过 Event 对象的生成、解释和处理来编排的。

理解和使用事件¶
作为开发者，你将主要与 Runner 产生的事件流进行交互。以下是如何理解并从中提取信息的方法：

Note

原语的特定参数或方法名称可能因 SDK 语言而略有不同（例如，Python 中的 event.content()，Java 中的 event.content().get().parts()）。详情请参阅特定语言的 API 文档。

识别事件来源和类型¶
通过检查以下内容快速确定事件代表什么：

谁发送的？ (event.author)
'user': 表示直接来自终端用户的输入。
'AgentName': 表示来自特定智能体的输出或操作（例如，'WeatherAgent'、'SummarizerAgent'）。
主要有效载荷是什么？ (event.content 和 event.content.parts)

文本： 表示对话消息。对于 Python，检查 event.content.parts[0].text 是否存在。对于 Java，检查 event.content() 是否存在，其 parts() 是否存在且不为空，以及第一个部分的 text() 是否存在。
工具调用请求： 检查 event.get_function_calls()。如果不为空，LLM 请求执行一个或多个工具。列表中的每个项目都有 .name 和 .args。
工具结果： 检查 event.get_function_responses()。如果不为空，此事件携带来自工具执行的结果。每个项目都有 .name 和 .response（工具返回的字典）。注意： 对于历史结构，content 内部的 role 通常是 'user'，但事件 author 通常是请求工具调用的智能体。
是流式输出吗？ (event.partial) 表示这是否是来自 LLM 的不完整文本块。

True: 后面还会有更多文本。
False 或 None/Optional.empty(): 这部分内容是完整的（尽管如果 turn_complete 也为 false，则整个轮次可能尚未完成）。



# 伪代码：基本事件识别 (Python)
# async for event in runner.run_async(...):
#     print(f"事件来源: {event.author}")
#
#     if event.content and event.content.parts:
#         if event.get_function_calls():
#             print("  类型: 工具调用请求")
#         elif event.get_function_responses():
#             print("  类型: 工具结果")
#         elif event.content.parts[0].text:
#             if event.partial:
#                 print("  类型: 流式文本块")
#             else:
#                 print("  类型: 完整文本消息")
#         else:
#             print("  类型: 其他内容 (例如，代码结果)")
#     elif event.actions and (event.actions.state_delta or event.actions.artifact_delta):
#         print("  类型: 状态/制品更新")
#     else:
#         print("  类型: 控制信号或其他")

提取关键信息¶
一旦你知道了事件类型，就可以访问相关数据：

文本内容： 在访问文本之前，请务必检查内容和部分是否存在。在 Python 中，它是 text = event.content.parts[0].text。

函数调用详情：




calls = event.get_function_calls()
if calls:
    for call in calls:
        tool_name = call.name
        arguments = call.args # 这通常是一个字典
        print(f"  工具：{tool_name}, 参数：{arguments}")
        # 应用程序可能会根据此信息分派执行

函数响应详情：




responses = event.get_function_responses()
if responses:
    for response in responses:
        tool_name = response.name
        result_dict = response.response # 工具返回的字典
        print(f"  工具结果：{tool_name} -> {result_dict}")

标识符：

event.id: 此特定事件实例的唯一 ID。
event.invocation_id: 此事件所属的整个用户请求到最终响应周期的 ID。用于日志记录和跟踪。
检测操作和副作用¶
event.actions 对象表示已发生或应发生的更改。在访问 event.actions 及其字段/方法之前，请务必检查它们是否存在。

状态更改： 为你提供一个键值对集合，表示在产生此事件的步骤期间修改的会话状态。



delta = event.actions.state_delta (一个 {key: value} 对的字典)。


if event.actions and event.actions.state_delta:
    print(f"  状态更改：{event.actions.state_delta}")
    # 如有必要，更新本地 UI 或应用程序状态

制品保存： 为你提供一个集合，指示保存了哪些制品及其新版本号（或相关的 Part 信息）。



artifact_changes = event.actions.artifact_delta (一个 {filename: version} 的字典)。


if event.actions and event.actions.artifact_delta:
    print(f"  制品已保存：{event.actions.artifact_delta}")
    # UI 可能会刷新制品列表

控制流信号： 检查布尔标志或字符串值：



event.actions.transfer_to_agent (string): 控制应传递给指定的智能体。
event.actions.escalate (bool): 循环应终止。
event.actions.skip_summarization (bool): 工具结果不应由 LLM 总结。

if event.actions:
    if event.actions.transfer_to_agent:
        print(f"  信号：转移到 {event.actions.transfer_to_agent}")
    if event.actions.escalate:
        print("信号：升级 (终止循环)")
    if event.actions.skip_summarization:
        print("  信号：跳过工具结果的总结")

判断事件是否为“最终”响应¶
使用内置的辅助方法 event.is_final_response() 来识别适合作为智能体一轮完整输出显示的事件。

目的： 从最终面向用户的消息中过滤掉中间步骤（如工具调用、部分流式文本、内部状态更新）。
何时为 True？
事件包含工具结果 (function_response) 且 skip_summarization 为 True。
事件包含对标记为 is_long_running=True 的工具的工具调用 (function_call)。在 Java 中，检查 longRunningToolIds 列表是否为空：
event.longRunningToolIds().isPresent() && !event.longRunningToolIds().get().isEmpty() 为 true。
或者，所有 以下条件都满足：
没有函数调用 (get_function_calls() 为空)。
没有函数响应 (get_function_responses() 为空)。
不是部分流块 (partial 不为 True)。
不以可能需要进一步处理/显示的代码执行结果结尾。
用法： 在你的应用程序逻辑中过滤事件流。




# 伪代码：在应用程序中处理最终响应 (Python)
# full_response_text = ""
# async for event in runner.run_async(...):
#     # 如需要，累积流式文本...
#     if event.partial and event.content and event.content.parts and event.content.parts[0].text:
#         full_response_text += event.content.parts[0].text
#
#     # 检查它是否是最终的可显示事件
#     if event.is_final_response():
#         print("\n--- 检测到最终输出 ---")
#         if event.content and event.content.parts and event.content.parts[0].text:
#              # 如果它是流的最后一部分，则使用累积的文本
#              final_text = full_response_text + (event.content.parts[0].text if not event.partial else "")
#              print(f"向用户显示：{final_text.strip()}")
#              full_response_text = "" # 重置累加器
#         elif event.actions and event.actions.skip_summarization and event.get_function_responses():
#              # 如需要，处理显示原始工具结果
#              response_data = event.get_function_responses()[0].response
#              print(f"显示原始工具结果：{response_data}")
#         elif hasattr(event, 'long_running_tool_ids') and event.long_running_tool_ids:
#              print("显示消息：工具正在后台运行...")
#         else:
#              # 如适用，处理其他类型的最终响应
#              print("显示：最终的非文本响应或信号。")

通过仔细检查事件的这些方面，你可以构建出能够对流经 ADK 系统的丰富信息做出适当反应的健壮应用程序。

事件如何流动：生成和处理¶
事件在不同的点被创建，并由框架系统地处理。理解这个流程有助于阐明如何管理操作和历史。

生成来源：

用户输入： Runner 通常将初始用户消息或对话中输入包装成一个 author='user' 的 Event。
智能体逻辑： 智能体（BaseAgent、LlmAgent）显式地 yield Event(...) 对象（设置 author=self.name）来传达响应或发出操作信号。
LLM 响应： ADK 模型集成层将原始 LLM 输出（文本、函数调用、错误）转换为 Event 对象，由调用智能体创作。
工具结果： 工具执行后，框架会生成一个包含 function_response 的 Event。author 通常是请求该工具的智能体，而 content 内部的 role 则为 LLM 历史设置为 'user'。
处理流程：

Yield/Return: 事件由其源生成并 yield (Python) 或 return/emit (Java)。
Runner 接收： 执行智能体的主 Runner 接收事件。
SessionService 处理： Runner 将事件发送到配置的 SessionService。这是一个关键步骤：
应用增量： 服务将 event.actions.state_delta 合并到 session.state 中，并根据 event.actions.artifact_delta 更新内部记录。（注意：实际的制品保存通常在调用 context.save_artifact 时更早发生）。
最终确定元数据： 如果不存在，则分配一个唯一的 event.id,可能会更新 event.timestamp。
持久化到历史： 将处理后的事件附加到 session.events 列表中。
外部 Yield: Runner 将处理后的事件向外 yield (Python) 或 return/emit (Java) 给调用应用程序（例如，调用 runner.run_async 的代码）。
此流程确保状态更改和历史记录与每个事件的通信内容一致地记录下来。

常见事件示例（说明性模式）¶
以下是你在流中可能看到的典型事件的简明示例：

用户输入：

{
  "author": "user",
  "invocation_id": "e-xyz...",
  "content": {"parts": [{"text": "预订下周二去伦敦的航班"}]}
  // actions 通常为空
}
智能体最终文本响应： (is_final_response() == True)

{
  "author": "TravelAgent",
  "invocation_id": "e-xyz...",
  "content": {"parts": [{"text": "好的，我可以帮忙。你能确认一下出发城市吗？"}]},
  "partial": false,
  "turn_complete": true
  // actions 可能有状态增量等。
}
智能体流式文本响应： (is_final_response() == False)

{
  "author": "SummaryAgent",
  "invocation_id": "e-abc...",
  "content": {"parts": [{"text": "该文件讨论了三个要点:"}]},
  "partial": true,
  "turn_complete": false
}
// ... 后面跟着更多 partial=True 的事件 ...
工具调用请求（由 LLM 发出）: (is_final_response() == False)

{
  "author": "TravelAgent",
  "invocation_id": "e-xyz...",
  "content": {"parts": [{"function_call": {"name": "find_airports", "args": {"city": "London"}}}]}
  // actions 通常为空
}
提供的工具结果（给 LLM）: (is_final_response() 取决于 skip_summarization)

{
  "author": "TravelAgent", // 作者是请求调用的智能体
  "invocation_id": "e-xyz...",
  "content": {
    "role": "user", // LLM 历史的角色
    "parts": [{"function_response": {"name": "find_airports", "response": {"result": ["LHR", "LGW", "STN"]}}}]
  }
  // actions 可能有 skip_summarization=True
}
仅状态/制品更新： (is_final_response() == False)

{
  "author": "InternalUpdater",
  "invocation_id": "e-def...",
  "content": null,
  "actions": {
    "state_delta": {"user_status": "verified"},
    "artifact_delta": {"verification_doc.pdf": 2}
  }
}
智能体转移信号： (is_final_response() == False)

{
  "author": "OrchestratorAgent",
  "invocation_id": "e-789...",
  "content": {"parts": [{"function_call": {"name": "transfer_to_agent", "args": {"agent_name": "BillingAgent"}}}]},
  "actions": {"transfer_to_agent": "BillingAgent"} // 由框架添加
}
循环升级信号： (is_final_response() == False)

{
  "author": "CheckerAgent",
  "invocation_id": "e-loop...",
  "content": {"parts": [{"text": "已达到最大重试次数。"}]}, // 可选内容
  "actions": {"escalate": true}
}
附加上下文和事件详情¶
除了核心概念之外，以下是一些关于上下文和事件的具体细节，对于某些用例很重要：

ToolContext.function_call_id（链接工具操作）:

当 LLM 请求一个工具 (FunctionCall) 时，该请求有一个 ID。提供给你工具函数的 ToolContext 包含此 function_call_id。
重要性： 此 ID 对于将身份验证等操作链接回发起它们的特定工具请求至关重要，尤其是在一轮中调用多个工具时。框架在内部使用此 ID。
状态/制品变更是如何记录的：

当你使用 CallbackContext 或 ToolContext 修改状态或保存制品时，这些更改不会立即写入持久存储。
相反，它们会填充 EventActions 对象中的 state_delta 和 artifact_delta 字段。
此 EventActions 对象附加到更改后生成的下一个事件（例如，智能体的响应或工具结果事件）。
SessionService.append_event 方法从传入事件中读取这些增量，并将它们应用于会话的持久状态和制品记录。这确保了更改与事件流按时间顺序绑定。
状态范围前缀（app:、user:、temp:）:

通过 context.state 管理状态时，你可以选择使用前缀：
app:my_setting: 表示与整个应用程序相关的状态（需要持久的 SessionService）。
user:user_preference: 表示与特定用户跨会话相关的状态（需要持久的 SessionService）。
temp:intermediate_result 或无前缀：通常是当前调用的会话特定或临时状态。
底层的 SessionService 决定如何处理这些前缀以实现持久性。
错误事件：

一个 Event 可以表示一个错误。检查 event.error_code 和 event.error_message 字段（从 LlmResponse 继承）。
错误可能源于 LLM（例如，安全过滤器、资源限制）,或者如果工具发生严重故障，则可能由框架打包。检查工具 FunctionResponse 内容以获取典型的工具特定错误。

// 示例错误事件（概念性）
{
  "author": "LLMAgent",
  "invocation_id": "e-err...",
  "content": null,
  "error_code": "SAFETY_FILTER_TRIGGERED",
  "error_message": "由于安全设置，响应被阻止。",
  "actions": {}
}
这些细节为涉及工具身份验证、状态持久性范围和事件流内错误处理的高级用例提供了更完整的画面。

使用事件的最佳实践¶
要在你的 ADK 应用程序中有效使用事件：

明确的作者身份： 在构建自定义智能体时，确保在历史记录中正确归属智能体操作。框架通常会为 LLM/工具事件正确处理作者身份。



在 BaseAgent 子类中使用 yield Event(author=self.name, ...)。


语义内容和操作： 使用 event.content 表示核心消息/数据（文本、函数调用/响应）。专门使用 event.actions 来表示副作用（状态/制品增量）或控制流（transfer、escalate、skip_summarization）。

幂等性意识： 理解 SessionService 负责应用 event.actions 中发出的状态/制品更改。虽然 ADK 服务旨在保持一致性，但如果你的应用程序逻辑重新处理事件，请考虑潜在的下游影响。
使用 is_final_response(): 在你的应用程序/UI 层中依赖此辅助方法来识别完整的、面向用户的文本响应。避免手动复制其逻辑。
利用历史记录： 会话的事件列表是你的主要调试工具。检查作者、内容和操作的顺序以跟踪执行并诊断问题。
使用元数据： 使用 invocation_id 来关联单个用户交互中的所有事件。使用 event.id 来引用特定的、唯一的发生。
将事件视为具有明确内容和操作目的的结构化消息，是构建、调试和管理 ADK 中复杂智能体行为的关键。