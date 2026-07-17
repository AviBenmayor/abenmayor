from crewai.tools import tool
from duckduckgo_search import DDGS


@tool("web_search")
def web_search(query: str) -> str:
    """Search the web for current information. Use specific queries for best results."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=6))
        if not results:
            return "No results found."
        return "\n---\n".join(
            f"**{r['title']}**\nURL: {r['href']}\n{r['body']}" for r in results
        )
    except Exception as e:
        return f"Search error: {e}"


@tool("search_news")
def search_news(query: str) -> str:
    """Search for recent news articles on a topic."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.news(query, max_results=8))
        if not results:
            return "No news found."
        return "\n---\n".join(
            f"**{r['title']}** ({r.get('date', 'recent')})\nSource: {r.get('source', '')}\nURL: {r['url']}\n{r['body']}"
            for r in results
        )
    except Exception as e:
        return f"News search error: {e}"
