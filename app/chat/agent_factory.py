from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm


def create_web_assistant(model_name: str) -> Agent:
    return Agent(
        name="summarix_web_assistant",
        model=LiteLlm(model=model_name),
        description="总结网页内容并回答用户问题的浏览器助手。",
        instruction=(
            "你是 Summarix 浏览器助手。你会基于用户提供的网页正文、网页标题、URL、截图或其他附件回答问题。"
            "默认使用简体中文和清晰 Markdown 输出，结构要利于在浏览器侧边栏阅读。"
            "回答要准确、简洁、有条理；无法从上下文确认的信息要明确说明，不要编造。"
            "如果用户要求总结网页，优先给一句话结论，再提炼主题、关键观点、事实依据和可行动结论。"
            "如果用户提供截图或图片，先说明可见内容，再结合网页上下文回答。"
            "适合使用列表、表格或代码块时可以使用，但不要为了装饰而使用复杂格式。"
        ),
    )
