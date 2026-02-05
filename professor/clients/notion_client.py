"""
Notion API client for knowledge database management.
"""
import requests
from datetime import datetime
from typing import List, Dict, Any, Optional
import sys
sys.path.append('..')
import config


class NotionClient:
    """Notion API client for knowledge database management."""

    BASE_URL = "https://api.notion.com/v1"
    NOTION_VERSION = "2022-06-28"

    def __init__(self, api_key: str = None, database_id: str = None):
        self.api_key = api_key or config.NOTION_API_KEY
        self.database_id = database_id or config.NOTION_DATABASE_ID
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Notion-Version": self.NOTION_VERSION
        }

    def query_database(self, filter_obj: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """Query the knowledge database."""
        url = f"{self.BASE_URL}/databases/{self.database_id}/query"
        payload = {}
        if filter_obj:
            payload["filter"] = filter_obj

        try:
            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()
            return response.json().get("results", [])
        except Exception as e:
            print(f"Error querying Notion database: {e}")
            return []

    def create_page(self, article: Dict[str, Any], relevance_score: float = 0.0) -> Optional[Dict]:
        """Create a new page in the database for an article."""
        url = f"{self.BASE_URL}/pages"

        properties = self._format_properties(article, relevance_score)
        payload = {
            "parent": {"database_id": self.database_id},
            "properties": properties
        }

        try:
            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            print(f"Error creating Notion page: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response: {e.response.text}")
            return None
        except Exception as e:
            print(f"Error creating Notion page: {e}")
            return None

    def _format_properties(self, article: Dict[str, Any], relevance_score: float) -> Dict[str, Any]:
        """Format article data for the existing Knowledge Base schema."""
        # Truncate title to 100 chars (Notion limit)
        title = article.get('title', 'Untitled')[:100]

        # Build explanation with URL and summary
        url = article.get('url', '')
        summary = article.get('summary', '')[:500]
        author = article.get('author', 'Unknown')
        explanation = f"Source: {url}\n\nAuthor: {author}\n\n{summary}"

        # Map relevance score to confidence level
        if relevance_score >= 0.8:
            confidence = "High"
        elif relevance_score >= 0.6:
            confidence = "Medium"
        else:
            confidence = "Low"

        # Map source to domain
        source = article.get('source', 'unknown').upper()
        domain = f"{config.CURRENT_TOPIC} - {source}"

        today = datetime.now().strftime('%Y-%m-%d')

        properties = {
            "Topic": {
                "title": [{"text": {"content": title}}]
            },
            "Explanation": {
                "rich_text": [{"text": {"content": explanation[:2000]}}]
            },
            "Domain": {
                "select": {"name": domain}
            },
            "Confidence": {
                "select": {"name": confidence}
            },
            "Questions": {
                "rich_text": [{"text": {"content": url}}]
            },
            "Times Reviewed": {
                "number": 0
            },
            "Last Reviewed": {
                "date": {"start": today}
            },
            "Next Review": {
                "date": {"start": today}
            }
        }

        return properties

    def add_articles(self, articles: List[Dict[str, Any]]) -> int:
        """Add multiple articles to Notion database."""
        added = 0
        for article in articles:
            score = article.get('relevance_score', 0.0)
            result = self.create_page(article, score)
            if result:
                added += 1
                print(f"  Added to Notion: {article.get('title', 'Unknown')[:50]}...")

        print(f"Added {added}/{len(articles)} articles to Notion")
        return added

    def create_knowledge_item(self, concept: Dict[str, Any]) -> Optional[Dict]:
        """
        Create a knowledge item (concept) in the database.

        Args:
            concept: Dict with topic, explanation, domain, test_question, etc.
        """
        url = f"{self.BASE_URL}/pages"

        # Calculate initial review date (tomorrow)
        from datetime import timedelta
        today = datetime.now().strftime('%Y-%m-%d')
        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        domain = concept.get('domain', config.CURRENT_TOPIC)

        properties = {
            "Topic": {
                "title": [{"text": {"content": concept.get('topic', 'Untitled')[:100]}}]
            },
            "Explanation": {
                "rich_text": [{"text": {"content": concept.get('explanation', '')[:2000]}}]
            },
            "Domain": {
                "select": {"name": domain}
            },
            "Confidence": {
                "select": {"name": concept.get('confidence', 'Low')}
            },
            "Questions": {
                "rich_text": [{"text": {"content": concept.get('test_question', '')[:2000]}}]
            },
            "Times Reviewed": {
                "number": 0
            },
            "Last Reviewed": {
                "date": {"start": today}
            },
            "Next Review": {
                "date": {"start": tomorrow}
            }
        }

        payload = {
            "parent": {"database_id": self.database_id},
            "properties": properties
        }

        try:
            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error creating knowledge item: {e}")
            return None

    def update_page(self, page_id: str, properties: Dict[str, Any]) -> Optional[Dict]:
        """Update properties of an existing page."""
        url = f"{self.BASE_URL}/pages/{page_id}"

        payload = {"properties": properties}

        try:
            response = requests.patch(url, headers=self.headers, json=payload)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error updating page: {e}")
            return None

    def update_after_review(self, page_id: str, passed: bool, times_reviewed: int) -> Optional[Dict]:
        """
        Update a knowledge item after a review session.

        Args:
            page_id: Notion page ID
            passed: Whether the user successfully recalled the item
            times_reviewed: Current times reviewed count
        """
        from datetime import timedelta

        # Calculate new values
        if passed:
            new_times = times_reviewed + 1
            # Determine confidence upgrade
            if new_times >= 5:
                confidence = "High"
            elif new_times >= 3:
                confidence = "Medium"
            else:
                confidence = "Low"
            # Calculate next review using spaced repetition
            intervals = {1: 1, 2: 3, 3: 7, 4: 14, 5: 30}
            days = intervals.get(min(new_times, 5), 30)
        else:
            new_times = 0
            confidence = "Low"
            days = 1  # Reset to tomorrow

        today = datetime.now().strftime('%Y-%m-%d')
        next_review = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')

        properties = {
            "Times Reviewed": {"number": new_times},
            "Confidence": {"select": {"name": confidence}},
            "Last Reviewed": {"date": {"start": today}},
            "Next Review": {"date": {"start": next_review}}
        }

        return self.update_page(page_id, properties)

    def get_items_due_for_review(self) -> List[Dict[str, Any]]:
        """Get all items due for review today or earlier."""
        today = datetime.now().strftime('%Y-%m-%d')

        filter_obj = {
            "and": [
                {
                    "property": "Next Review",
                    "date": {
                        "on_or_before": today
                    }
                },
                {
                    "property": "Domain",
                    "select": {
                        "contains": config.CURRENT_TOPIC
                    }
                }
            ]
        }

        return self.query_database(filter_obj)

    def get_low_confidence_items(self) -> List[Dict[str, Any]]:
        """Get items marked as Low confidence in current domain."""
        filter_obj = {
            "and": [
                {
                    "property": "Confidence",
                    "select": {
                        "equals": "Low"
                    }
                },
                {
                    "property": "Domain",
                    "select": {
                        "contains": config.CURRENT_TOPIC
                    }
                }
            ]
        }

        return self.query_database(filter_obj)
