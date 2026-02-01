# Category mapping from Plaid categories to budget categories
CATEGORY_MAPPING = {
    # Transportation
    "TRANSPORTATION": "Auto & Transport",
    "TRANSPORTATION_TAXIS_AND_RIDE_SHARES": "Auto & Transport",
    "TRANSPORTATION_PUBLIC_TRANSIT": "Auto & Transport",
    "TRANSPORTATION_GAS": "Auto & Transport",
    "TRANSPORTATION_PARKING": "Auto & Transport",
    
    # Bills & Utilities
    "UTILITIES": "Bills & Utilities",
    "UTILITIES_ELECTRIC": "Bills & Utilities",
    "UTILITIES_GAS": "Bills & Utilities",
    "UTILITIES_WATER": "Bills & Utilities",
    "UTILITIES_INTERNET_AND_CABLE": "Bills & Utilities",
    "UTILITIES_PHONE": "Bills & Utilities",
    
    # Dining
    "FOOD_AND_DRINK": "Dining & Drinks",
    "FOOD_AND_DRINK_RESTAURANTS": "Dining & Drinks",
    "FOOD_AND_DRINK_FAST_FOOD": "Dining & Drinks",
    "FOOD_AND_DRINK_COFFEE": "Dining & Drinks",
    "FOOD_AND_DRINK_BAR": "Dining & Drinks",
    
    # Groceries
    "FOOD_AND_DRINK_GROCERIES": "Groceries",
    
    # Entertainment
    "ENTERTAINMENT": "Entertainment & Rec.",
    "ENTERTAINMENT_MOVIES_AND_MUSIC": "Entertainment & Rec.",
    "ENTERTAINMENT_SPORTING_EVENTS": "Entertainment & Rec.",
    "ENTERTAINMENT_RECREATION": "Entertainment & Rec.",
    
    # Shopping
    "GENERAL_MERCHANDISE": "Shopping",
    "GENERAL_MERCHANDISE_CLOTHING_AND_ACCESSORIES": "Shopping",
    "GENERAL_MERCHANDISE_DEPARTMENT_STORES": "Shopping",
    "GENERAL_MERCHANDISE_ONLINE_MARKETPLACES": "Shopping",
    "GENERAL_MERCHANDISE_ELECTRONICS": "Software & Tech",
    
    # Health
    "MEDICAL": "Medical",
    "MEDICAL_DENTAL_CARE": "Medical",
    "MEDICAL_EYE_CARE": "Medical",
    "MEDICAL_PHARMACY": "Medical",
    "MEDICAL_PRIMARY_CARE": "Medical",
    
    # Personal Care
    "PERSONAL_CARE": "Personal Care",
    "PERSONAL_CARE_GYMS_AND_FITNESS_CENTERS": "Health & Wellness",
    "PERSONAL_CARE_HAIR_AND_BEAUTY": "Personal Care",
    
    # Home
    "HOME_IMPROVEMENT": "Home & Garden",
    "HOME_IMPROVEMENT_FURNITURE": "Home & Garden",
    "HOME_IMPROVEMENT_HARDWARE": "Home & Garden",
    
    # Rent/Mortgage
    "RENT_AND_UTILITIES": "Rent",
    "LOAN_PAYMENTS": "Loan Payment",
    "LOAN_PAYMENTS_MORTGAGE_PAYMENT": "Rent",
    
    # Transfer/Savings
    "TRANSFER_OUT": "Savings Transfer",
    "TRANSFER_OUT_INVESTMENT_AND_RETIREMENT_FUNDS": "Investment",
    
    # Gifts
    "GENERAL_SERVICES_GIFTS_AND_DONATIONS": "Gifts",
    
    # Travel
    "TRAVEL": "Travel & Vacation",
    "TRAVEL_FLIGHTS": "Travel & Vacation",
    "TRAVEL_LODGING": "Travel & Vacation",
    
    # Fees
    "BANK_FEES": "Fees",
    "BANK_FEES_ATM_FEES": "Fees",
    "BANK_FEES_OVERDRAFT_FEES": "Fees",
    
    # Default
    "OTHER": "Other",
}

def map_transaction_to_budget_category(transaction: dict) -> str:
    """Map a Plaid transaction to a budget category"""
    # Get the detailed category from Plaid
    personal_finance = transaction.get('personal_finance_category', {})
    detailed = personal_finance.get('detailed', '')
    primary = personal_finance.get('primary', '')
    
    # Try detailed first, then primary, then default to Other
    if detailed in CATEGORY_MAPPING:
        return CATEGORY_MAPPING[detailed]
    elif primary in CATEGORY_MAPPING:
        return CATEGORY_MAPPING[primary]
    else:
        return "Other"
