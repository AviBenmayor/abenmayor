"""
Newsletter Generator - Daily learning review with spaced repetition.

Generates a personalized daily newsletter that includes:
- Review These Today (items due for spaced repetition)
- Test Yourself (active recall questions)
- Connections You Might Have Missed (synthesis across concepts)
- This Week's Focus (low confidence items needing attention)
- Supplementary Reading (high-relevance articles, if any)
"""
from anthropic import Anthropic
from datetime import datetime
from typing import List, Dict, Any, Optional
import config
from clients.notion_client import NotionClient
from pipeline.spaced_repetition import SpacedRepetition


class NewsletterGenerator:
    """Generates daily learning newsletters from Notion knowledge base."""

    def __init__(self):
        self.notion = NotionClient()
        self.spaced_rep = SpacedRepetition()
        self.claude = None
        if config.ANTHROPIC_API_KEY:
            self.claude = Anthropic(api_key=config.ANTHROPIC_API_KEY)

    def generate_newsletter(self, articles: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """
        Generate the daily learning newsletter.

        Args:
            articles: Optional list of high-relevance articles to include

        Returns:
            Dict with newsletter sections and content
        """
        print("Generating daily learning newsletter...")

        # Fetch knowledge base items from Notion
        knowledge_items = self._fetch_knowledge_items()
        print(f"  Found {len(knowledge_items)} items in knowledge base")

        # Get items due for review
        due_items = self.spaced_rep.get_items_due_for_review(knowledge_items)
        print(f"  {len(due_items)} items due for review today")

        # Get low confidence items
        low_confidence = self.spaced_rep.get_low_confidence_items(knowledge_items)
        print(f"  {len(low_confidence)} low-confidence items need attention")

        # Generate sections
        newsletter = {
            'date': datetime.now().strftime('%A, %B %d, %Y'),
            'domain': config.CURRENT_TOPIC,
            'review_items': self._format_review_section(due_items[:5]),
            'test_questions': self._generate_test_questions(due_items[:5]),
            'connections': self._find_connections(knowledge_items) if self.claude else [],
            'focus_items': self._format_focus_section(low_confidence[:3]),
            'supplementary_articles': articles or [],
            'stats': {
                'total_concepts': len(knowledge_items),
                'due_today': len(due_items),
                'low_confidence': len(low_confidence)
            }
        }

        return newsletter

    def _fetch_knowledge_items(self) -> List[Dict[str, Any]]:
        """Fetch all items from the Notion knowledge base."""
        if not self.notion.headers:
            print("  Warning: Notion not configured")
            return []

        try:
            import requests
            url = f"https://api.notion.com/v1/databases/{config.NOTION_DATABASE_ID}/query"

            # Query for items in current domain
            payload = {
                "filter": {
                    "property": "Domain",
                    "select": {
                        "contains": config.CURRENT_TOPIC
                    }
                },
                "page_size": 100
            }

            response = requests.post(url, headers=self.notion.headers, json=payload)

            if response.status_code != 200:
                print(f"  Error querying Notion: {response.status_code}")
                return []

            data = response.json()
            items = []

            for page in data.get('results', []):
                props = page.get('properties', {})
                item = self._parse_notion_item(props)
                if item:
                    items.append(item)

            return items

        except Exception as e:
            print(f"  Error fetching from Notion: {e}")
            return []

    def _parse_notion_item(self, props: Dict) -> Optional[Dict[str, Any]]:
        """Parse Notion page properties into knowledge item."""
        try:
            # Extract title
            title_prop = props.get('Topic', {})
            title = ''
            if title_prop.get('title'):
                title = title_prop['title'][0]['text']['content'] if title_prop['title'] else ''

            # Extract explanation
            explanation_prop = props.get('Explanation', {})
            explanation = ''
            if explanation_prop.get('rich_text'):
                explanation = explanation_prop['rich_text'][0]['text']['content'] if explanation_prop['rich_text'] else ''

            # Extract confidence
            confidence_prop = props.get('Confidence', {})
            confidence = confidence_prop.get('select', {}).get('name', 'Low') if confidence_prop.get('select') else 'Low'

            # Extract dates
            last_reviewed = None
            if props.get('Last Reviewed', {}).get('date'):
                last_reviewed = props['Last Reviewed']['date'].get('start')

            next_review = None
            if props.get('Next Review', {}).get('date'):
                next_review = props['Next Review']['date'].get('start')

            # Extract times reviewed
            times_reviewed = props.get('Times Reviewed', {}).get('number', 0) or 0

            # Extract questions (used for test questions)
            questions_prop = props.get('Questions', {})
            questions = ''
            if questions_prop.get('rich_text'):
                questions = questions_prop['rich_text'][0]['text']['content'] if questions_prop['rich_text'] else ''

            return {
                'topic': title,
                'explanation': explanation,
                'confidence': confidence,
                'last_reviewed': last_reviewed,
                'next_review': next_review,
                'times_reviewed': times_reviewed,
                'questions': questions
            }

        except Exception as e:
            return None

    def _format_review_section(self, items: List[Dict]) -> List[Dict]:
        """Format items for the Review These Today section."""
        review_items = []
        for item in items:
            times = item.get('times_reviewed', 0)
            stage = self.spaced_rep.format_interval_description(times)

            review_items.append({
                'topic': item.get('topic', 'Unknown'),
                'explanation': item.get('explanation', '')[:300],
                'stage': stage,
                'days_overdue': item.get('_days_overdue', 0)
            })

        return review_items

    def _generate_test_questions(self, items: List[Dict]) -> List[Dict]:
        """Generate test questions for active recall."""
        questions = []

        for item in items:
            # Use stored questions if available
            stored_q = item.get('questions', '')
            if stored_q and not stored_q.startswith('http'):
                questions.append({
                    'topic': item.get('topic', 'Unknown'),
                    'question': stored_q
                })
            elif self.claude and item.get('explanation'):
                # Generate question with Claude
                q = self._generate_question_for_concept(
                    item.get('topic', ''),
                    item.get('explanation', '')
                )
                if q:
                    questions.append({
                        'topic': item.get('topic', 'Unknown'),
                        'question': q
                    })

        return questions

    def _generate_question_for_concept(self, topic: str, explanation: str) -> Optional[str]:
        """Use Claude to generate a test question for a concept."""
        if not self.claude:
            return None

        try:
            response = self.claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=150,
                messages=[{
                    "role": "user",
                    "content": f"""Generate ONE test question to verify understanding of this concept.

Topic: {topic}
Explanation: {explanation}

The question should:
- Test genuine understanding, not just recall
- Be answerable in 1-2 sentences
- Help identify if someone truly grasps the concept

Return ONLY the question, nothing else."""
                }]
            )
            return response.content[0].text.strip()
        except Exception as e:
            return None

    def _find_connections(self, items: List[Dict]) -> List[str]:
        """Use Claude to find connections between concepts."""
        if not self.claude or len(items) < 2:
            return []

        # Get a sample of concepts to analyze
        sample = items[:10]
        concepts_text = "\n".join([
            f"- {item.get('topic', '')}: {item.get('explanation', '')[:100]}"
            for item in sample if item.get('topic')
        ])

        if not concepts_text:
            return []

        try:
            response = self.claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=400,
                messages=[{
                    "role": "user",
                    "content": f"""Look at these concepts from my knowledge base and identify 1-2 non-obvious connections between them.

Concepts:
{concepts_text}

For each connection:
1. Name the concepts being connected
2. Explain the relationship (2-3 sentences)
3. Why this connection matters

Be specific and insightful. Skip obvious connections."""
                }]
            )
            # Split response into separate insights
            text = response.content[0].text.strip()
            return [text] if text else []
        except Exception as e:
            return []

    def _format_focus_section(self, items: List[Dict]) -> List[Dict]:
        """Format low-confidence items for This Week's Focus."""
        focus_items = []
        for item in items:
            focus_items.append({
                'topic': item.get('topic', 'Unknown'),
                'explanation': item.get('explanation', '')[:200],
                'confidence': item.get('confidence', 'Low'),
                'last_reviewed': item.get('last_reviewed', 'Never')
            })
        return focus_items

    def format_as_text(self, newsletter: Dict) -> str:
        """Format newsletter as plain text."""
        lines = []
        lines.append(f"{'='*60}")
        lines.append(f"YOUR DAILY LEARNING BRIEF — {newsletter['date']}")
        lines.append(f"Domain: {newsletter['domain']}")
        lines.append(f"{'='*60}")
        lines.append("")

        # Stats
        stats = newsletter.get('stats', {})
        lines.append(f"📊 {stats.get('total_concepts', 0)} concepts | "
                    f"{stats.get('due_today', 0)} due today | "
                    f"{stats.get('low_confidence', 0)} need attention")
        lines.append("")

        # Review section
        if newsletter.get('review_items'):
            lines.append("📚 REVIEW THESE TODAY")
            lines.append("-" * 40)
            for i, item in enumerate(newsletter['review_items'], 1):
                lines.append(f"\n{i}. {item['topic']} ({item['stage']})")
                lines.append(f"   {item['explanation']}")
                if item.get('days_overdue', 0) > 0:
                    lines.append(f"   ⚠️ {item['days_overdue']} days overdue")
            lines.append("")

        # Test questions
        if newsletter.get('test_questions'):
            lines.append("❓ TEST YOURSELF")
            lines.append("-" * 40)
            for i, q in enumerate(newsletter['test_questions'], 1):
                lines.append(f"\n{i}. [{q['topic']}]")
                lines.append(f"   {q['question']}")
            lines.append("")

        # Connections
        if newsletter.get('connections'):
            lines.append("🔗 CONNECTIONS YOU MIGHT HAVE MISSED")
            lines.append("-" * 40)
            for connection in newsletter['connections']:
                lines.append(f"\n{connection}")
            lines.append("")

        # Focus items
        if newsletter.get('focus_items'):
            lines.append("🎯 THIS WEEK'S FOCUS")
            lines.append("-" * 40)
            for item in newsletter['focus_items']:
                lines.append(f"\n• {item['topic']} (Confidence: {item['confidence']})")
                lines.append(f"  Last reviewed: {item['last_reviewed']}")
                lines.append(f"  {item['explanation']}")
            lines.append("")

        # Supplementary articles
        if newsletter.get('supplementary_articles'):
            lines.append("📰 SUPPLEMENTARY READING (0.9+ relevance)")
            lines.append("-" * 40)
            for article in newsletter['supplementary_articles'][:5]:
                lines.append(f"\n• {article.get('title', 'Unknown')}")
                lines.append(f"  {article.get('url', '')}")
            lines.append("")

        lines.append("=" * 60)
        lines.append("Keep learning! The compound effect is real. 🚀")

        return "\n".join(lines)

    def format_as_html(self, newsletter: Dict) -> str:
        """Format newsletter as HTML email."""
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #333; }}
        h1 {{ color: #1a1a1a; border-bottom: 2px solid #007AFF; padding-bottom: 10px; }}
        h2 {{ color: #007AFF; margin-top: 30px; }}
        .stats {{ background: #f5f5f7; padding: 15px; border-radius: 8px; margin: 20px 0; }}
        .item {{ background: #fff; border-left: 4px solid #007AFF; padding: 15px; margin: 15px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .question {{ background: #fffbeb; border-left: 4px solid #f59e0b; padding: 15px; margin: 15px 0; }}
        .connection {{ background: #f0fdf4; border-left: 4px solid #22c55e; padding: 15px; margin: 15px 0; }}
        .focus {{ background: #fef2f2; border-left: 4px solid #ef4444; padding: 15px; margin: 15px 0; }}
        .article {{ padding: 10px 0; border-bottom: 1px solid #eee; }}
        .overdue {{ color: #ef4444; font-weight: bold; }}
        .stage {{ color: #666; font-size: 0.9em; }}
        a {{ color: #007AFF; }}
    </style>
</head>
<body>
    <h1>📚 Your Daily Learning Brief</h1>
    <p><strong>{newsletter['date']}</strong> | Domain: {newsletter['domain']}</p>

    <div class="stats">
        📊 <strong>{newsletter['stats']['total_concepts']}</strong> concepts in your knowledge base |
        <strong>{newsletter['stats']['due_today']}</strong> due for review today |
        <strong>{newsletter['stats']['low_confidence']}</strong> need attention
    </div>
"""

        # Review section
        if newsletter.get('review_items'):
            html += "<h2>📚 Review These Today</h2>"
            for i, item in enumerate(newsletter['review_items'], 1):
                overdue = f'<span class="overdue">⚠️ {item["days_overdue"]} days overdue</span>' if item.get('days_overdue', 0) > 0 else ''
                html += f"""
    <div class="item">
        <strong>{i}. {item['topic']}</strong> <span class="stage">({item['stage']})</span> {overdue}
        <p>{item['explanation']}</p>
    </div>
"""

        # Test questions
        if newsletter.get('test_questions'):
            html += "<h2>❓ Test Yourself</h2>"
            for i, q in enumerate(newsletter['test_questions'], 1):
                html += f"""
    <div class="question">
        <strong>{i}. {q['topic']}</strong>
        <p>{q['question']}</p>
    </div>
"""

        # Connections
        if newsletter.get('connections'):
            html += "<h2>🔗 Connections You Might Have Missed</h2>"
            for connection in newsletter['connections']:
                html += f"""
    <div class="connection">
        <p>{connection}</p>
    </div>
"""

        # Focus items
        if newsletter.get('focus_items'):
            html += "<h2>🎯 This Week's Focus</h2>"
            for item in newsletter['focus_items']:
                html += f"""
    <div class="focus">
        <strong>{item['topic']}</strong> (Confidence: {item['confidence']})
        <p><em>Last reviewed: {item['last_reviewed']}</em></p>
        <p>{item['explanation']}</p>
    </div>
"""

        # Supplementary articles
        if newsletter.get('supplementary_articles'):
            html += "<h2>📰 Supplementary Reading</h2>"
            html += "<p><em>High-relevance articles (0.9+ score) for deeper exploration:</em></p>"
            for article in newsletter['supplementary_articles'][:5]:
                html += f"""
    <div class="article">
        <a href="{article.get('url', '#')}">{article.get('title', 'Unknown')}</a>
        <p style="color: #666; font-size: 0.9em;">{article.get('source', '')} | {article.get('author', '')}</p>
    </div>
"""

        html += """
    <hr style="margin-top: 30px;">
    <p style="color: #666; text-align: center;">
        Keep learning! Knowledge compounds. 🚀<br>
        <em>Generated by Professor</em>
    </p>
</body>
</html>
"""
        return html


if __name__ == "__main__":
    generator = NewsletterGenerator()
    newsletter = generator.generate_newsletter()
    print(generator.format_as_text(newsletter))
