b) LLM 驱动委派 (智能体转移)¶
利用 LlmAgent 的理解能力动态地将任务路由到层次结构内的其他适合智能体。

机制： 智能体的 LLM 生成一个特定的函数调用：transfer_to_agent(agent_name='target_agent_name')。
处理： AutoFlow(当存在子智能体或未禁止转移时默认使用) 拦截此调用。它使用 root_agent.find_agent() 识别目标智能体，并更新 InvocationContext 以切换执行焦点。
需求： 调用的 LlmAgent 需要清晰的 instructions 来说明何时转移，潜在目标智能体需要不同的 description 以便 LLM 做出明智的决策。可以在 LlmAgent 上配置转移范围 (父级、子智能体、同级)。
性质： 基于 LLM 解释的动态、灵活路由。

Python
Typescript
Go
Java

# 概念设置：LLM 转移
from google.adk.agents import LlmAgent


booking_agent = LlmAgent(name="Booker", description="Handles flight and hotel bookings.")
info_agent = LlmAgent(name="Info", description="Provides general information and answers questions.")


coordinator = LlmAgent(
    name="Coordinator",
    model="gemini-flash-latest",
    instruction="你是一个助手。将预订任务委派给 Booker，将信息请求委派给 Info。",
    description="主协调器。",
    # 此时通常隐式使用 AutoFlow
    sub_agents=[booking_agent, info_agent]
)
# 如果 coordinator 收到 "Book a flight"，其 LLM 应生成：
# FunctionCall(name='transfer_to_agent', args={'agent_name': 'Booker'})
# 然后 ADK 框架将执行路由到 booking_agent。