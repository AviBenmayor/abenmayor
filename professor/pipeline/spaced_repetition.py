"""
Spaced Repetition Module - Calculate review intervals using SM-2 inspired algorithm.

Intervals:
- 1st review: 1 day
- 2nd review: 3 days
- 3rd review: 7 days
- 4th review: 14 days
- 5th+: 30 days
- Failed recall: Reset to 1 day
"""
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import sys
sys.path.append('..')
import config


class SpacedRepetition:
    """Manages spaced repetition scheduling for knowledge items."""

    def __init__(self):
        self.intervals = config.SPACED_REPETITION_INTERVALS
        self.reset_days = config.FAILED_RECALL_RESET_DAYS

    def calculate_next_review(self, times_reviewed: int, passed: bool = True) -> datetime:
        """
        Calculate the next review date based on review count and pass/fail.

        Args:
            times_reviewed: How many times this item has been reviewed
            passed: Whether the user successfully recalled the information

        Returns:
            datetime of next scheduled review
        """
        if not passed:
            # Failed recall - reset to short interval
            days = self.reset_days
        else:
            # Use interval based on review count (cap at max interval)
            review_num = min(times_reviewed + 1, max(self.intervals.keys()))
            days = self.intervals.get(review_num, 30)

        return datetime.now() + timedelta(days=days)

    def get_items_due_for_review(self, items: list) -> list:
        """
        Filter items that are due for review (Next Review <= today).

        Args:
            items: List of knowledge items with 'next_review' date

        Returns:
            List of items due for review, sorted by urgency
        """
        today = datetime.now().date()
        due_items = []

        for item in items:
            next_review = item.get('next_review')
            if next_review:
                # Handle string dates
                if isinstance(next_review, str):
                    try:
                        next_review = datetime.strptime(next_review, '%Y-%m-%d').date()
                    except ValueError:
                        continue
                elif isinstance(next_review, datetime):
                    next_review = next_review.date()

                if next_review <= today:
                    item['_days_overdue'] = (today - next_review).days
                    due_items.append(item)

        # Sort by most overdue first
        due_items.sort(key=lambda x: x.get('_days_overdue', 0), reverse=True)
        return due_items

    def get_low_confidence_items(self, items: list, days_threshold: int = 3) -> list:
        """
        Get items marked Low confidence that haven't been reviewed recently.

        Args:
            items: List of knowledge items
            days_threshold: Days since last review to consider "stale"

        Returns:
            List of low-confidence items needing attention
        """
        threshold_date = (datetime.now() - timedelta(days=days_threshold)).date()
        low_confidence = []

        for item in items:
            confidence = item.get('confidence', '').lower()
            if confidence == 'low':
                last_reviewed = item.get('last_reviewed')
                if last_reviewed:
                    if isinstance(last_reviewed, str):
                        try:
                            last_reviewed = datetime.strptime(last_reviewed, '%Y-%m-%d').date()
                        except ValueError:
                            continue
                    elif isinstance(last_reviewed, datetime):
                        last_reviewed = last_reviewed.date()

                    if last_reviewed < threshold_date:
                        low_confidence.append(item)

        return low_confidence

    def format_interval_description(self, times_reviewed: int) -> str:
        """Get human-readable description of review stage."""
        stages = {
            0: "New concept",
            1: "1st review (learning)",
            2: "2nd review (consolidating)",
            3: "3rd review (reinforcing)",
            4: "4th review (long-term)",
            5: "Maintenance review"
        }
        return stages.get(min(times_reviewed, 5), "Maintenance review")

    def update_after_review(self, item: Dict[str, Any], passed: bool) -> Dict[str, Any]:
        """
        Update an item after a review session.

        Args:
            item: The knowledge item
            passed: Whether recall was successful

        Returns:
            Updated item with new dates and counts
        """
        times_reviewed = item.get('times_reviewed', 0)

        if passed:
            times_reviewed += 1
            # Upgrade confidence on successful recall
            current_confidence = item.get('confidence', 'Low')
            if times_reviewed >= 3 and current_confidence == 'Low':
                item['confidence'] = 'Medium'
            elif times_reviewed >= 5 and current_confidence == 'Medium':
                item['confidence'] = 'High'
        else:
            # Reset on failed recall
            times_reviewed = 0
            item['confidence'] = 'Low'

        item['times_reviewed'] = times_reviewed
        item['last_reviewed'] = datetime.now().strftime('%Y-%m-%d')
        item['next_review'] = self.calculate_next_review(times_reviewed, passed).strftime('%Y-%m-%d')

        return item
