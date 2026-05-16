### 监控系统集成需求总结：PLG + LangWatch + 自动化部署

注意，如果在没有这些组件的情况下部署，不启用相关功能即可，系统仍然可以正常运行，也没有性能损耗。

#### 1. 项目背景与架构

* **后端技术栈**：Python (FastAPI) + Google ADK (Agent Development Kit) + LiteLLM。
* **核心链路**：流式 AI 聊天响应。
* **部署目标**：通过 `docker-compose` 实现监控组件与业务后端的一键本地化部署。

#### 2. 核心监控组件需求

* **Prometheus (Metrics)**：
* **基础监控**：QPS、响应延迟（P99/P95）、HTTP 状态码分布。
* **AI 业务监控**：LLM 调用成功率、首字延迟（TTFT）、Token 消耗量、不同 Provider（如 OpenAI vs Claude）的分布。
* **埋点工具**：使用 `prometheus-fastapi-instrumentator` 自动插桩。


* **Loki (Logging)**：
* **日志格式**：后端应用必须输出标准 **JSON 日志**。
* **采集方式**：通过 Promtail 采集容器日志并注入 Loki。


* **LangWatch (LLM Observability)**：
* **追踪 (Tracing)**：利用 `openinference-instrumentation-google-adk` 实现对 ADK 智能体运行、工具调用和模型请求的自动追踪。
* **反馈回路**：接入用户显式反馈（👍/👎），将其关联至具体的 `trace_id` 用于质量评估。
* **高级功能**：配置预置的“护栏 (Guardrails)”和“提示词管理”。


* **Grafana (Visualization)**：
* **集成看板**：统一展示 Prometheus 指标、Loki 日志以及基础硬件状态。
* **数据联动**：配置数据源自动关联。



#### 3. 自动化部署与配置需求

* **Docker 部署**：提供一份包含所有组件（FastAPI App, Prometheus, Loki, Promtail, Grafana, LangWatch [Self-hosted]）的 `docker-compose.yml`。
* **配置文件生成**：
* `prometheus.yml`：自动发现后端服务并设置抓取频率。
* `promtail-config.yaml`：配置路径映射以读取 Docker 容器日志。

* **持久化**：为所有数据库（Prometheus, Loki, Grafana, LangWatch DB）配置命名卷（Volumes）。

#### 4. 业务逻辑集成需求

* **Trace ID 传递**：在流式输出中通过 Header 或消息体返回 `trace_id`。
* **反馈接口**：实现 `POST /api/feedback` 接口，同时向 LangWatch 写入 Score 并向 Prometheus 增加 Counter 计数。


LangWatch 我给你准备了官方的部署docker-compose文件和官方的adk示例:

LangWatch 是一个开源的 LLMOps 平台，用于可观测性、评估和提示词优化。它通过 OpenInference 插桩 (Instrumentation) 为 ADK 智能体提供全面的追踪 (Tracing) 功能，让你能够在开发和生产环境中监控、调试并改进你的智能体。

概览¶
LangWatch 利用其内置的 OpenTelemetry 支持来捕获来自 ADK 的追踪信息，为你提供：

自动追踪 —— 在完整的上下文中捕获每一次智能体运行、工具调用和模型请求
在线评估 —— 对生产环境流量的质量和安全性进行持续评分
护栏 (Guardrails) —— 实时阻断或修改有害响应
提示词管理 —— 通过内置的 A/B 测试对提示词进行版本控制、测试和优化
数据集与实验 —— 从真实的追踪信息中构建评估集并运行批处理实验
安装¶
安装所需的包：


pip install langwatch openinference-instrumentation-google-adk google-adk
设置¶
在 langwatch.ai 注册或自托管 (Self-hosting) 该平台，然后设置你的 API 密钥：


export LANGWATCH_API_KEY="your-langwatch-api-key"
export GOOGLE_API_KEY="your-gemini-api-key"
初始化追踪：


import langwatch
from openinference.instrumentation.google_adk import GoogleADKInstrumentor

langwatch.setup(
    instrumentors=[GoogleADKInstrumentor()]
)
就这样。现在，所有 ADK 智能体的活动都将被追踪并自动发送到你的 LangWatch 控制面板。

观测¶
初始化追踪后，像往常一样运行你的 ADK 智能体，所有的交互都会出现在 LangWatch 中：


import langwatch
from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.genai import types
from openinference.instrumentation.google_adk import GoogleADKInstrumentor

langwatch.setup(
    instrumentors=[GoogleADKInstrumentor()]
)

# 定义一个工具
def get_weather(city: str) -> dict:
    """获取指定城市的当前天气报告。

    参数：
        city (str): 城市名称。

    返回：
        dict: 状态、结果或错误消息。
    """
    if city.lower() == "new york":
        return {
            "status": "success",
            "report": (
                "纽约天气晴朗，气温 25 摄氏度（77 华氏度）。"
            ),
        }
    else:
        return {
            "status": "error",
            "error_message": f"无法获取 '{city}' 的天气信息。",
        }

# 创建带有工具的智能体
agent = Agent(
    name="weather_agent",
    model="gemini-flash-latest",
    description="回答关于天气问题的智能体。",
    instruction="你必须使用可用工具来寻找答案。",
    tools=[get_weather],
)

app_name = "weather_app"
user_id = "test_user"
session_id = "test_session"
runner = InMemoryRunner(agent=agent, app_name=app_name)
session_service = runner.session_service

await session_service.create_session(
    app_name=app_name,
    user_id=user_id,
    session_id=session_id,
)

# 运行智能体 —— 所有交互都将被追踪
async for event in runner.run_async(
    user_id=user_id,
    session_id=session_id,
    new_message=types.Content(
        role="user",
        parts=[types.Part(text="纽约的天气怎么样？")],
    ),
):
    if event.is_final_response():
        print(event.content.parts[0].text.strip())
添加自定义元数据¶
使用 @langwatch.trace() 装饰器为你的追踪添加额外的上下文：


@langwatch.trace(name="ADK 天气智能体")
def run_agent(user_message: str):
    current_trace = langwatch.get_current_trace()
    if current_trace:
        current_trace.update(
            metadata={
                "user_id": "user_123",
                "agent_name": "weather_agent",
                "environment": "production",
            }
        )

    user_msg = types.Content(
        role="user", parts=[types.Part(text=user_message)]
    )
    for event in runner.run(
        user_id="demo-user",
        session_id="demo-session",
        new_message=user_msg,
    ):
        if event.is_final_response():
            return event.content.parts[0].text

    return "没有生成响应"