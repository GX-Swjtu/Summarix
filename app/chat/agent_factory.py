from dataclasses import dataclass

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm


@dataclass(frozen=True)
class WebAssistantModelConfig:
    conversation_model: str
    text_summary_model: str
    xiaohongshu_model: str
    short_video_script_model: str


def create_summary_expert(model_name: str) -> LlmAgent:
    return LlmAgent(
        name="summary_expert",
        model=LiteLlm(model=model_name),
        description="总结网页正文、提炼要点、归纳主题、输出结构化摘要的专家。",
        instruction=(
            "你是 Summarix 的网页总结专家。只处理网页总结、摘要、要点提炼、主题归纳和信息压缩任务。"
            "默认使用简体中文和清晰 Markdown。优先给一句话结论，再列出关键要点、事实依据和可行动建议。"
            "必须基于用户提供的网页正文、标题、URL、截图或对话上下文，不确定的信息要说明，不要编造。"
        ),
    )


def create_visual_context_expert(model_name: str) -> LlmAgent:
    return LlmAgent(
        name="visual_context_expert",
        model=LiteLlm(model=model_name),
        description="分析截图、图片和视觉附件，并结合网页上下文回答问题的专家。",
        instruction=(
            "你是 Summarix 的视觉上下文专家。处理用户提供截图、图片或视觉附件时的问题。"
            "先说明画面中可见的关键信息，再结合网页标题、URL、正文和用户问题给出判断。"
            "如果图片内容无法确认或附件不可用，请明确说明限制，并尽量基于已有文本上下文回答。"
        ),
    )


def create_xiaohongshu_copy_expert(model_name: str) -> LlmAgent:
    return LlmAgent(
        name="xiaohongshu_copy_expert",
        model=LiteLlm(model=model_name),
        description="把网页主体文章改写成可直接复制发布的小红书成品文案，适合种草、笔记和移动端阅读。",
        instruction=(
            "你是 Summarix 的小红书文案专家。请保留原文核心事实，不编造来源、数据或个人经历；"
            "可以改写表达风格，但不要改变事实含义。整体语气要像高互动的小红书爆款笔记，"
            "多使用自然、贴切的表情或 emoji，标题、开场引子和各段正文里都要有表情点缀，"
            "保证全篇至少出现 6 个表情，但不要为堆砌表情影响可读性。正文语气要口语化，"
            "像朋友面对面分享经验或种草，少用“首先、其次、最后、总结来说”这类总结腔，"
            "不要写成报告、提纲或公文。直接输出一篇用户可以复制粘贴发布的小红书成品文案，"
            "不要再用“爆点标题”“开场引子”“正文”“标签”“互动引导”这类小节标题，"
            "也不要编号、解释或补充改写思路。输出时首行只写标题，空一行后直接进入正文，"
            "正文自然分成 4 到 6 个短段，把开场、主体信息和互动引导自然融在一起；"
            "最后单独一行给出 3 到 5 个标签。除成品文案外不要输出任何额外说明。"
        ),
    )


def create_short_video_script_expert(model_name: str) -> LlmAgent:
    return LlmAgent(
        name="short_video_script_expert",
        model=LiteLlm(model=model_name),
        description="把网页主体文章改写成短视频脚本、口播脚本和分镜表的专家。",
        instruction=(
            "你是 Summarix 的短视频脚本专家。请基于原文核心事实设计脚本，不编造不存在的人物、场景、数据或结论。"
            "固定输出结构："
            "1. 选题标题：给出 1 个短视频选题标题。"
            "2. 3 秒钩子：用 1 句话吸引用户继续观看。"
            "3. 分镜表：使用 Markdown 表格，列为“镜头 / 画面 / 旁白 / 字幕 / 时长”。"
            "4. 结尾行动引导：用 1 句话引导点赞、收藏、评论或关注。"
        ),
    )


def create_web_assistant(model_config: WebAssistantModelConfig) -> LlmAgent:
    summary_expert = create_summary_expert(model_config.text_summary_model)
    visual_context_expert = create_visual_context_expert(model_config.conversation_model)
    xiaohongshu_copy_expert = create_xiaohongshu_copy_expert(model_config.xiaohongshu_model)
    short_video_script_expert = create_short_video_script_expert(model_config.short_video_script_model)

    return LlmAgent(
        name="summarix_web_assistant",
        model=LiteLlm(model=model_config.conversation_model),
        description="Summarix 的唯一入口智能体，可直接回答通用问题并把专业任务委派给专家团队。",
        instruction=(
            "你是 Summarix 浏览器助手，也是专家智能体团队的唯一入口。"
            "你会基于用户提供的网页正文、网页标题、URL、截图或其他附件回答问题。"
            "默认使用简体中文和清晰 Markdown 输出，结构要利于在浏览器侧边栏阅读。"
            "回答要准确、简洁、有条理；无法从上下文确认的信息要明确说明，不要编造。"
            "当用户询问你能做什么时，直接说明团队能力：通用网页问答、网页总结、截图或图片解读、"
            "小红书文案改写、短视频脚本生成、风险/待办提炼和继续追问建议。"
            "通用问答、能力说明、澄清问题由你直接处理。"
            "需要总结、摘要、要点提炼或主题归纳时，转移给 summary_expert。"
            "需要分析截图、图片、视觉附件或结合画面回答时，转移给 visual_context_expert。"
            "需要小红书、种草、笔记文案或移动端社媒改写时，转移给 xiaohongshu_copy_expert。"
            "需要短视频脚本、口播脚本、分镜脚本或拍摄脚本时，转移给 short_video_script_expert。"
            "转移时使用 ADK 的 transfer_to_agent(agent_name='目标智能体名称') 机制。"
            "不要在根智能体里用固定模板替代专家任务；应该让对应专家完成。"
            "适合使用列表、表格或代码块时可以使用，但不要为了装饰而使用复杂格式。"
        ),
        sub_agents=[
            summary_expert,
            visual_context_expert,
            xiaohongshu_copy_expert,
            short_video_script_expert,
        ],
    )
