from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm


def create_web_assistant(model_name: str) -> Agent:
    return Agent(
        name="summarix_web_assistant",
        model=LiteLlm(model=model_name),
        description="总结网页内容并回答用户问题的浏览器助手。",
        instruction=(
            "你是 Summarix 浏览器助手。你会基于用户提供的网页正文、网页标题、URL、截图或其他附件回答问题。"
            "回答要准确、简洁、有条理。无法从上下文确认的信息要明确说明，不要编造。"
            "如果用户要求总结网页，优先提炼主题、关键观点、事实依据和可行动结论。"
        ),
    )
