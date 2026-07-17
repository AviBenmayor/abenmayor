from crewai.tools import tool
import config


@tool("get_notion_tasks")
def get_notion_tasks(status: str = "In Progress") -> str:
    """
    Fetch tasks or pages from the Notion tasks database.
    Args:
        status: Filter by status — "In Progress", "Todo", "Done", or "all"
    """
    if not config.NOTION_API_KEY or not config.NOTION_TASKS_DB_ID:
        return "Notion not configured — set NOTION_API_KEY and NOTION_TASKS_DB_ID in .env"

    try:
        from notion_client import Client
        notion = Client(auth=config.NOTION_API_KEY)

        filters = []
        if status.lower() != "all":
            filters = [{"property": "Status", "status": {"equals": status}}]

        query_args = {"database_id": config.NOTION_TASKS_DB_ID}
        if filters:
            query_args["filter"] = {"and": filters}

        response = notion.databases.query(**query_args)
        pages = response.get("results", [])

        if not pages:
            return f"No tasks found with status '{status}'."

        items = []
        for page in pages[:15]:
            props = page.get("properties", {})
            title = _get_title(props)
            page_status = _get_status(props)
            items.append(f"- {title} [{page_status}]")

        return f"Notion tasks ({status}):\n" + "\n".join(items)
    except Exception as e:
        return f"Notion error: {e}"


def _get_title(props: dict) -> str:
    for key in ["Name", "Title", "Task", "title"]:
        if key in props:
            title_list = props[key].get("title", [])
            if title_list:
                return title_list[0].get("plain_text", "Untitled")
    return "Untitled"


def _get_status(props: dict) -> str:
    for key in ["Status", "status"]:
        if key in props:
            val = props[key]
            if val.get("status"):
                return val["status"].get("name", "Unknown")
            if val.get("select"):
                return val["select"].get("name", "Unknown")
    return "Unknown"
