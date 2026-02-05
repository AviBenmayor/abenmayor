"""
LLM-based relevance scoring for content using Claude.
"""
import json
import re
from typing import List, Dict, Any
from anthropic import Anthropic
import sys
sys.path.append('..')
import config


class RelevanceScorer:
    """Scores content relevance to current topic using Claude."""

    def __init__(self):
        self.scoring_available = False
        if config.ANTHROPIC_API_KEY:
            self.client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
            print("Claude client initialized for relevance scoring")
        else:
            self.client = None
            print("Warning: ANTHROPIC_API_KEY not found. Relevance scoring disabled.")

    def score_articles(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Score a batch of articles for topic relevance."""
        # Default score that passes the filter (0.7 > 0.6 threshold)
        DEFAULT_SCORE = 0.7

        if not self.client:
            # Without Claude, give all articles a passing default score
            print("  No API client - using default scores")
            for article in articles:
                article['relevance_score'] = DEFAULT_SCORE
            return articles

        if not articles:
            return articles

        # Process in batches of 10
        batch_size = 10
        scored_articles = []

        for i in range(0, len(articles), batch_size):
            batch = articles[i:i+batch_size]
            print(f"  Scoring batch {i//batch_size + 1} ({len(batch)} articles)...")
            scores = self._score_batch(batch)

            for j, article in enumerate(batch):
                # Use default passing score if API scoring failed
                article['relevance_score'] = scores.get(j, DEFAULT_SCORE)
                if not scores:
                    self.scoring_available = False
                else:
                    self.scoring_available = True
                scored_articles.append(article)

        return scored_articles

    def _score_batch(self, articles: List[Dict[str, Any]]) -> Dict[int, float]:
        """Score a batch of articles using Claude."""
        articles_text = []
        for i, a in enumerate(articles):
            title = a.get('title', 'No title')
            summary = a.get('summary', '')[:200]
            articles_text.append(f"{i}. {title}\n   {summary}")

        prompt = f"""Rate how relevant each article is to the topic: {config.CURRENT_TOPIC}

Topic Description: {config.TOPIC_DESCRIPTION}

Articles:
{chr(10).join(articles_text)}

For each article (by index), provide a relevance score from 0.0 to 1.0:
- 1.0 = Directly about GTM engineering, startup sales, go-to-market strategies, revenue operations
- 0.7-0.9 = Related to sales tech, startup growth, business development, PLG
- 0.4-0.6 = Tangentially related (general business, tech industry, startups)
- 0.0-0.3 = Not relevant

Return JSON only, no other text: {{"scores": {{"0": 0.8, "1": 0.3, ...}}}}"""

        try:
            response = self.client.messages.create(
                model="claude-3-5-haiku-latest",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}]
            )

            # Extract the text content
            content = response.content[0].text

            # Parse JSON from response (handle potential extra text)
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return {int(k): float(v) for k, v in result.get("scores", {}).items()}
            else:
                print(f"  Could not parse JSON from response: {content[:100]}")
                return {}
        except Exception as e:
            print(f"  Error scoring batch: {e}")
            return {}
