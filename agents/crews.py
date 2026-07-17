from datetime import date
from crewai import Task, Crew, Process
from agents import make_researcher, make_strategist, make_coordinator


def run_morning_brief() -> str:
    """Daily morning briefing: GTM news + Notion priorities + email delivery."""
    researcher = make_researcher()
    strategist = make_strategist()
    coordinator = make_coordinator()

    today = date.today().strftime("%B %d, %Y")

    fetch_news = Task(
        description=f"""Search for the most relevant GTM Engineering news and signals from the past 48 hours.
        Look for: new sales tools, RevOps trends, PLG strategies, startup GTM announcements,
        CRM/outbound tool updates, and any M&A or funding in the GTM tech space.
        Today is {today}. Return 4–6 key items with source URLs and a one-sentence takeaway each.""",
        expected_output="A bulleted list of 4–6 GTM news items, each with title, URL, and key takeaway.",
        agent=researcher,
    )

    fetch_tasks = Task(
        description="""Check Notion for current tasks and priorities. Look at 'In Progress' and 'Todo' items.
        Summarize what's on the plate today and flag anything that looks overdue or high priority.""",
        expected_output="A short summary of active Notion tasks, highlighting top 3 priorities.",
        agent=coordinator,
    )

    synthesize = Task(
        description=f"""Create a sharp, executive-style morning briefing for {today}.
        Combine the GTM news intel and the Notion task priorities into a single cohesive brief.
        Format:
        1. Top Priorities (from Notion tasks) — 3 bullet points max
        2. GTM Intelligence — 4–6 news items with takeaways
        3. Suggested Focus — one paragraph on where to put energy today
        Make it scannable, direct, and useful. No fluff.""",
        expected_output="A complete morning briefing in HTML format, ready to email.",
        agent=strategist,
        context=[fetch_news, fetch_tasks],
    )

    send = Task(
        description=f"""Send the morning briefing as an email.
        Subject: 'GTM Morning Brief — {today}'
        Use the synthesized briefing content as the email body.
        Wrap it in clean HTML with a simple header.""",
        expected_output="Confirmation that the email was sent successfully.",
        agent=coordinator,
        context=[synthesize],
    )

    crew = Crew(
        agents=[researcher, coordinator, strategist],
        tasks=[fetch_news, fetch_tasks, synthesize, send],
        process=Process.sequential,
        verbose=True,
    )
    return crew.kickoff()


def run_prospect_research(company: str, contact: str = "") -> str:
    """Research a prospect company and generate personalized outreach."""
    researcher = make_researcher()
    strategist = make_strategist()

    research_company = Task(
        description=f"""Research the company: {company}
        Find:
        - What they do and their current stage/size
        - Their current GTM motion (sales-led vs PLG, inbound vs outbound)
        - Signals they might need GTM engineering help (recent funding, headcount growth, new product launches)
        - Tech stack hints (job postings, LinkedIn, BuiltWith)
        - Recent news or announcements
        {f'Also research this contact: {contact}' if contact else ''}
        Be specific. Find real evidence, not guesses.""",
        expected_output="Detailed research brief on the company with GTM pain point hypothesis and tech stack notes.",
        agent=researcher,
    )

    research_contacts = Task(
        description=f"""Search LinkedIn and the web for decision-makers at {company} relevant to GTM Engineering.
        Look for: VP of Sales, Head of RevOps, CTO, VP of Marketing, or whoever owns GTM infrastructure.
        Find their name, title, and any public content they've shared (posts, talks, articles).""",
        expected_output="List of 2–3 key contacts at the company with titles and any relevant context.",
        agent=researcher,
    )

    draft_outreach = Task(
        description=f"""Write a cold outreach email to {company} for Avi Benmayor, fractional GTM Engineering consultant.

        Use the research to make this highly personalized. The email should:
        - Open with a specific, relevant observation about {company} (not generic flattery)
        - Connect that observation to a GTM pain point Avi can solve
        - Make a clear, low-friction ask (15-min call, not a demo)
        - Be under 150 words total
        - Sound human, not like a template

        Also write a short research summary (1 paragraph) that Avi can keep as reference before the call.""",
        expected_output="Personalized cold email draft + one-paragraph research summary.",
        agent=strategist,
        context=[research_company, research_contacts],
    )

    crew = Crew(
        agents=[researcher, strategist],
        tasks=[research_company, research_contacts, draft_outreach],
        process=Process.sequential,
        verbose=True,
    )
    return crew.kickoff()


def run_content_generator(topic: str, format: str = "linkedin") -> str:
    """Generate thought leadership content on a GTM Engineering topic."""
    researcher = make_researcher()
    strategist = make_strategist()

    research_angle = Task(
        description=f"""Research the topic: "{topic}"
        Find: recent takes from GTM leaders on this topic, data points or stats that support a strong POV,
        any contrarian angles or underappreciated insights, and examples from real companies.
        Focus on what's genuinely interesting or surprising — not conventional wisdom.""",
        expected_output="Research notes with 3–5 key insights, data points, and source URLs.",
        agent=researcher,
    )

    create_content = Task(
        description=f"""Create {format} content about: "{topic}"

        Format guidelines:
        - LinkedIn post: 150–250 words, starts with a hook (not "I'm excited to share"),
          uses short paragraphs, ends with a question or call to action, no hashtag spam (max 2)
        - Newsletter section: 300–500 words, has a clear structure, includes a practical takeaway
        - Thread (Twitter/X): 5–8 tweets, each punchy and self-contained

        Write from Avi's POV as a fractional GTM Engineer. Take a specific, defensible stance.
        Don't be generic. Say something that only someone with real GTM Engineering experience would say.""",
        expected_output=f"Complete {format} content, ready to post or share.",
        agent=strategist,
        context=[research_angle],
    )

    crew = Crew(
        agents=[researcher, strategist],
        tasks=[research_angle, create_content],
        process=Process.sequential,
        verbose=True,
    )
    return crew.kickoff()
