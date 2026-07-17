import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from crewai.tools import tool
import config


@tool("send_email")
def send_email(subject: str, body_html: str) -> str:
    """
    Send an email via Gmail. Use for delivering briefings and research outputs.
    Args:
        subject: Email subject line
        body_html: HTML body content (use <h2>, <p>, <ul> tags for formatting)
    """
    if not all([config.SENDER_EMAIL, config.SENDER_PASSWORD, config.RECIPIENT_EMAIL]):
        return "Email not configured — set SENDER_EMAIL, SENDER_PASSWORD, RECIPIENT_EMAIL in .env"

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = config.SENDER_EMAIL
        msg["To"] = config.RECIPIENT_EMAIL
        msg["Subject"] = subject

        plain = body_html.replace("<br>", "\n").replace("</p>", "\n").replace("</h2>", "\n").replace("</h3>", "\n")
        import re
        plain = re.sub(r"<[^>]+>", "", plain).strip()

        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        with smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT) as server:
            server.starttls()
            server.login(config.SENDER_EMAIL, config.SENDER_PASSWORD)
            server.send_message(msg)

        return f"Email sent to {config.RECIPIENT_EMAIL}"
    except Exception as e:
        return f"Failed to send email: {e}"
