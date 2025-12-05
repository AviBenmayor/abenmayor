import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Any

class Notifier:
    def __init__(self):
        self.sender_email = os.getenv("EMAIL_SENDER")
        self.password = os.getenv("EMAIL_PASSWORD")
        self.recipient_email = os.getenv("EMAIL_RECIPIENT")

    def send_notification(self, opportunities: List[Dict[str, Any]]):
        if not opportunities:
            return

        print(f"Found {len(opportunities)} opportunities!")
        
        # Construct message body
        body = f"Found {len(opportunities)} Arbitrage Opportunities:\n\n"
        for opp in opportunities:
            body += f"--- {opp['type']} ---\n"
            body += f"Strategy: {opp['strategy']}\n"
            body += f"Profit: ${opp['profit']:.2f} (ROI: {opp['roi']:.2f}%)\n"
            body += f"Market A: {opp['market_a']['title']} ({opp['market_a']['url']})\n"
            body += f"Market B: {opp['market_b']['title']} ({opp['market_b']['url']})\n\n"

        print(body)

        if self.sender_email and self.password and self.recipient_email:
            try:
                msg = MIMEMultipart()
                msg['From'] = self.sender_email
                msg['To'] = self.recipient_email
                msg['Subject'] = f"Arbitrage Alert: {len(opportunities)} Opportunities Found"

                msg.attach(MIMEText(body, 'plain'))

                # Connect to Gmail SMTP server (defaulting to Gmail for now, can be configurable)
                # Using port 587 for TLS
                with smtplib.SMTP('smtp.gmail.com', 587) as server:
                    server.starttls()
                    server.login(self.sender_email, self.password)
                    server.send_message(msg)
                
                print(f"Email sent to {self.recipient_email}")
            except Exception as e:
                print(f"Failed to send email: {e}")
        else:
            print("Email credentials not set. Skipping email notification.")

