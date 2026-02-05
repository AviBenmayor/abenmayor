"""
Content processing, deduplication, and persistence.
"""
import csv
from typing import List, Dict, Any, Set
import sys
sys.path.append('..')
import config


class ContentProcessor:
    """Processes, deduplicates, and persists content."""

    def __init__(self):
        self.seen_urls: Set[str] = set()
        self._load_existing_articles()

    def _load_existing_articles(self):
        """Load URLs of previously seen articles."""
        try:
            with open(config.ARTICLES_FILE, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    url = row.get('url', '')
                    if url:
                        self.seen_urls.add(url)
            print(f"Loaded {len(self.seen_urls)} existing article URLs")
        except FileNotFoundError:
            print("No existing articles file found - starting fresh")

    def deduplicate(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate articles."""
        unique = []
        for article in articles:
            url = article.get('url', '')
            if url and url not in self.seen_urls:
                self.seen_urls.add(url)
                unique.append(article)

        removed = len(articles) - len(unique)
        if removed > 0:
            print(f"Deduplicated: removed {removed} duplicates, {len(unique)} unique")
        return unique

    def filter_by_relevance(self, articles: List[Dict[str, Any]], min_score: float = None) -> List[Dict[str, Any]]:
        """Filter articles by minimum relevance score."""
        min_score = min_score or config.MIN_RELEVANCE_SCORE
        filtered = [a for a in articles if a.get('relevance_score', 0) >= min_score]
        removed = len(articles) - len(filtered)
        print(f"Filtered by relevance (>= {min_score}): kept {len(filtered)}, removed {removed}")
        return filtered

    def save_articles(self, articles: List[Dict[str, Any]]):
        """Append articles to CSV file."""
        if not articles:
            print("No articles to save")
            return

        file_exists = config.ARTICLES_FILE.exists()
        fieldnames = ['url', 'title', 'source', 'author', 'published_at',
                      'summary', 'relevance_score', 'fetched_at']

        with open(config.ARTICLES_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()

            for article in articles:
                row = {k: str(article.get(k, ''))[:500] for k in fieldnames}
                writer.writerow(row)

        print(f"Saved {len(articles)} articles to {config.ARTICLES_FILE}")

    def get_top_articles(self, articles: List[Dict[str, Any]], limit: int = None) -> List[Dict[str, Any]]:
        """Get top articles sorted by relevance score."""
        limit = limit or config.MAX_ARTICLES_IN_DIGEST
        sorted_articles = sorted(
            articles,
            key=lambda x: x.get('relevance_score', 0),
            reverse=True
        )
        return sorted_articles[:limit]
