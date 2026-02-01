from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TransactionScheduler:
    def __init__(self, banking_client):
        self.banking_client = banking_client
        self.scheduler = BackgroundScheduler()
        
    def sync_daily_transactions(self):
        """Daily job to sync transactions from Plaid"""
        logger.info(f"Starting daily transaction sync at {datetime.now()}")
        try:
            result = self.banking_client.sync_transactions()
            logger.info(f"Daily sync complete: {result}")
        except Exception as e:
            logger.error(f"Error during daily sync: {e}")
    
    def start(self):
        """Start the scheduler"""
        # Schedule daily sync at 2 AM
        self.scheduler.add_job(
            self.sync_daily_transactions,
            'cron',
            hour=2,
            minute=0,
            id='daily_transaction_sync'
        )
        
        self.scheduler.start()
        logger.info("Transaction scheduler started. Daily sync scheduled for 2:00 AM.")
    
    def stop(self):
        """Stop the scheduler"""
        self.scheduler.shutdown()
        logger.info("Transaction scheduler stopped.")
