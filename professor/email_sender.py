"""
Email sender for daily digest via SMTP.
"""
import smtplib
import csv
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import List, Dict, Any
import config


class EmailSender:
    """Sends daily digest emails via SMTP."""

    def __init__(self):
        self.smtp_server = config.SMTP_SERVER
        self.smtp_port = config.SMTP_PORT
        self.sender_email = config.SENDER_EMAIL
        self.sender_password = config.SENDER_PASSWORD
        self.recipient_email = config.RECIPIENT_EMAIL

    def send_digest(self, articles: List[Dict[str, Any]]) -> bool:
        """Send daily digest email with top articles."""
        if not all([self.sender_email, self.sender_password, self.recipient_email]):
            print("Email credentials not configured. Skipping email.")
            return False

        if not articles:
            print("No articles to send.")
            return False

        # Sort by relevance score and limit
        articles = sorted(articles, key=lambda x: x.get('relevance_score', 0), reverse=True)
        articles = articles[:config.MAX_ARTICLES_IN_DIGEST]

        subject = f"Professor Daily Digest: {config.CURRENT_TOPIC} - {datetime.now().strftime('%B %d, %Y')}"

        # Build email body
        html_body = self._build_html_digest(articles)
        text_body = self._build_text_digest(articles)

        try:
            msg = MIMEMultipart('alternative')
            msg['From'] = self.sender_email
            msg['To'] = self.recipient_email
            msg['Subject'] = subject

            msg.attach(MIMEText(text_body, 'plain'))
            msg.attach(MIMEText(html_body, 'html'))

            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.send_message(msg)

            print(f"Digest sent to {self.recipient_email}")
            self._log_sent_digest(len(articles))
            return True
        except Exception as e:
            print(f"Failed to send email: {e}")
            return False

    def _build_html_digest(self, articles: List[Dict[str, Any]]) -> str:
        """Build HTML email body."""
        items_html = ""
        for i, article in enumerate(articles, 1):
            score = article.get('relevance_score', 0)
            source = article.get('source', 'unknown').upper()
            items_html += f"""
            <div style="margin-bottom: 24px; padding: 16px; border-left: 4px solid #4A90A4; background: #f9f9f9;">
                <h3 style="margin: 0 0 8px 0; font-size: 16px;">
                    <a href="{article.get('url', '#')}" style="color: #333; text-decoration: none;">
                        {article.get('title', 'Untitled')}
                    </a>
                </h3>
                <p style="color: #666; margin: 0 0 8px 0; font-size: 13px;">
                    {source} | {article.get('author', 'Unknown')[:50]} |
                    Relevance: {score:.0%}
                </p>
                <p style="color: #444; margin: 0; font-size: 14px; line-height: 1.5;">
                    {article.get('summary', '')[:300]}...
                </p>
            </div>
            """

        return f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background: #fff;">
            <div style="border-bottom: 3px solid #4A90A4; padding-bottom: 16px; margin-bottom: 24px;">
                <h1 style="color: #333; margin: 0 0 8px 0; font-size: 24px;">
                    Professor Daily Digest
                </h1>
                <h2 style="color: #666; margin: 0; font-size: 16px; font-weight: normal;">
                    Topic: {config.CURRENT_TOPIC}
                </h2>
                <p style="color: #888; margin: 8px 0 0 0; font-size: 13px;">
                    {datetime.now().strftime('%B %d, %Y')}
                </p>
            </div>

            {items_html}

            <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
            <p style="color: #999; font-size: 12px; text-align: center;">
                Found {len(articles)} relevant articles today.
            </p>
        </body>
        </html>
        """

    def _build_text_digest(self, articles: List[Dict[str, Any]]) -> str:
        """Build plain text email body."""
        lines = [
            f"PROFESSOR DAILY DIGEST - {config.CURRENT_TOPIC}",
            f"{datetime.now().strftime('%B %d, %Y')}",
            "=" * 50,
            ""
        ]

        for i, article in enumerate(articles, 1):
            lines.append(f"{i}. {article.get('title', 'Untitled')}")
            lines.append(f"   Source: {article.get('source', '').upper()}")
            lines.append(f"   Relevance: {article.get('relevance_score', 0):.0%}")
            lines.append(f"   {article.get('url', '')}")
            lines.append("")

        lines.append("=" * 50)
        lines.append(f"Found {len(articles)} relevant articles today.")

        return "\n".join(lines)

    def _log_sent_digest(self, article_count: int):
        """Log sent digest to CSV."""
        file_exists = config.SENT_DIGESTS_FILE.exists()

        with open(config.SENT_DIGESTS_FILE, 'a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(['sent_at', 'topic', 'article_count'])
            writer.writerow([datetime.now().isoformat(), config.CURRENT_TOPIC, article_count])

    def send_learning_newsletter(self, newsletter: Dict[str, Any], html_content: str, text_content: str) -> bool:
        """
        Send the daily learning newsletter with spaced repetition content.

        Args:
            newsletter: Newsletter data dict from NewsletterGenerator
            html_content: Pre-formatted HTML content
            text_content: Pre-formatted plain text content

        Returns:
            True if sent successfully
        """
        if not all([self.sender_email, self.sender_password, self.recipient_email]):
            print("Email credentials not configured. Skipping email.")
            return False

        subject = f"📚 Daily Learning Brief: {config.CURRENT_TOPIC} - {newsletter.get('date', 'Today')}"

        try:
            msg = MIMEMultipart('alternative')
            msg['From'] = self.sender_email
            msg['To'] = self.recipient_email
            msg['Subject'] = subject

            msg.attach(MIMEText(text_content, 'plain'))
            msg.attach(MIMEText(html_content, 'html'))

            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.send_message(msg)

            stats = newsletter.get('stats', {})
            print(f"Learning newsletter sent to {self.recipient_email}")
            print(f"  - {stats.get('due_today', 0)} items due for review")
            print(f"  - {len(newsletter.get('test_questions', []))} test questions")
            print(f"  - {len(newsletter.get('supplementary_articles', []))} supplementary articles")

            self._log_newsletter(newsletter)
            return True

        except Exception as e:
            print(f"Failed to send newsletter: {e}")
            return False

    def _log_newsletter(self, newsletter: Dict[str, Any]):
        """Log sent newsletter to CSV."""
        log_file = config.DATA_DIR / "sent_newsletters.csv"
        file_exists = log_file.exists()

        stats = newsletter.get('stats', {})

        with open(log_file, 'a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(['sent_at', 'topic', 'concepts_reviewed', 'due_items', 'low_confidence', 'articles'])
            writer.writerow([
                datetime.now().isoformat(),
                config.CURRENT_TOPIC,
                stats.get('total_concepts', 0),
                stats.get('due_today', 0),
                stats.get('low_confidence', 0),
                len(newsletter.get('supplementary_articles', []))
            ])
