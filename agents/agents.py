from crewai import Agent, LLM
from tools.search import web_search, search_news
from tools.email_sender import send_email
from tools.notion import get_notion_tasks
import config

_llm = LLM(model=f"openai/{config.OPENAI_MODEL}", api_key=config.OPENAI_API_KEY)

_base_backstory = config.CONSULTING_CONTEXT


def make_researcher() -> Agent:
    return Agent(
        role="GTM Intelligence Researcher",
        goal="Gather accurate, current intelligence to support a fractional GTM Engineering consultant",
        backstory=_base_backstory + """
You are a specialist research analyst with deep knowledge of the GTM Engineering landscape.
You excel at finding company intel, identifying pain points, tracking market trends, and
surfacing signals that create consulting opportunities. Be thorough, cite sources, and
always focus on what's actionable.""",
        tools=[web_search, search_news],
        llm=_llm,
        verbose=True,
        max_iter=6,
    )


def make_strategist() -> Agent:
    return Agent(
        role="GTM Content Strategist",
        goal="Transform research into compelling outreach messages, proposals, and thought leadership content",
        backstory=_base_backstory + """
You are a senior GTM strategist who has helped dozens of B2B SaaS startups scale from 0 to $10M ARR.
You write crisp, personalized outreach that gets responses. Your thought leadership content
establishes authority. You understand that a fractional GTM Engineer's value prop is rare:
technical depth + go-to-market strategy in one person. Make that shine in every piece you write.""",
        tools=[],
        llm=_llm,
        verbose=True,
    )


def make_coordinator() -> Agent:
    return Agent(
        role="Executive Operations Coordinator",
        goal="Track priorities, surface what needs attention, and deliver all outputs to the right place",
        backstory=_base_backstory + """
You are a world-class executive coordinator. You keep projects on track, synthesize information
into clear priorities, and ensure nothing falls through the cracks. When you send an email,
it's polished and formatted beautifully. When you report on Notion tasks, you give context
not just status.""",
        tools=[get_notion_tasks, send_email],
        llm=_llm,
        verbose=True,
    )
