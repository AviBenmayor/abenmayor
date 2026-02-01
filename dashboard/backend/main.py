from fastapi import FastAPI, HTTPException
from typing import Optional
from finance.banking import BankingClient
from finance.fidelity import FidelityClient
from finance.budget import BudgetManager
from finance.analytics import FinanceAnalytics
from health.whoop import WhoopClient
from health.apple_health import AppleHealthParser
from fastapi.middleware.cors import CORSMiddleware
from config import config

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    print(f"GLOBAL ERROR: {exc}")
    import traceback
    traceback.print_exc()
    return HTTPException(status_code=500, detail="Internal Server Error")

# Initialize Clients
banking_client = BankingClient()
fidelity_client = FidelityClient()
whoop_client = WhoopClient()
apple_health = AppleHealthParser()
budget_manager = BudgetManager()
analytics = FinanceAnalytics()

# Initialize and start scheduler
from scheduler import TransactionScheduler
transaction_scheduler = TransactionScheduler(banking_client)
transaction_scheduler.start()

@app.get("/")
def read_root():
    return {"message": "Welcome to the Personal Data Dashboard API"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}

@app.get("/callback")
def oauth_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    """
    Generic OAuth Redirect URL.
    Register: http://localhost:8000/callback
    """
    if error:
         return {"error": error}
         
    if code:
        # Attempt to exchange code for Whoop Token
        # NOTE: In a real app we'd check 'state' to know which provider this is for
        # For now, we assume it's Whoop since that's what we built
        token_response = whoop_client.exchange_token(code)
        
        if "error" in token_response:
             return {"message": "Token exchange failed", "details": token_response}
             
        return {
            "message": "Authentication Successful! You can close this window.",
            "token_preview": "****" + str(whoop_client.access_token)[-4:] if whoop_client.access_token else "None"
        }
    
    return {
        "message": "OAuth Callback received",
        "code": code,
        "state": state,
        "error": error
    }

@app.get("/finance/banking/transactions")
def get_banking_transactions(days: int = 30):
    return banking_client.get_transactions(days)

@app.get("/finance/banking/balances")
def get_banking_balances():
    return banking_client.get_balances()

@app.get("/finance/net-worth-history")
def get_net_worth_history():
    return banking_client.get_net_worth_history()

@app.get("/finance/budget")
def get_budget():
    return budget_manager.get_budget()

from fastapi import UploadFile, File
import shutil
import tempfile

@app.post("/finance/budget/upload")
async def upload_budget(file: UploadFile = File(...)):
    # Save uploaded file temporarily
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name
    
    try:
        # Parse based on file extension
        if file.filename.endswith('.xlsx') or file.filename.endswith('.xls'):
            categories = budget_manager.parse_excel(tmp_path)
        elif file.filename.endswith('.csv'):
            categories = budget_manager.parse_csv(tmp_path)
        else:
            return {"error": "Unsupported file format. Please upload .xlsx, .xls, or .csv"}
        
        if categories:
            budget_manager.update_budget(categories)
            return {"success": True, "categories": categories}
        else:
            return {"error": "No valid budget data found in file"}
    finally:
        # Clean up temp file
        os.unlink(tmp_path)

@app.get("/finance/budget/daily-tracking")
def get_daily_budget_tracking(days: int = 30):
    """Get yesterday's spending compared to daily budget allowance"""
    transactions = banking_client.get_transactions(days)
    return budget_manager.get_daily_tracking(transactions)

# Transaction Sync Endpoints
@app.post("/finance/sync")
def sync_transactions(days: int = None):
    """Manually trigger transaction sync from Plaid to database"""
    return banking_client.sync_transactions(days)

# Analytics Endpoints
@app.get("/finance/analytics/monthly")
def get_monthly_analytics(year: int, month: int):
    """Get monthly spending report"""
    return analytics.get_monthly_report(year, month)

@app.get("/finance/analytics/yearly")
def get_yearly_analytics(year: int):
    """Get yearly spending report"""
    return analytics.get_yearly_report(year)

@app.get("/finance/analytics/trends")
def get_spending_trends(months: int = 6):
    """Get spending trends for last N months"""
    return analytics.get_spending_trends(months)

@app.get("/finance/analytics/ytd")
def get_ytd_analytics(year: int):
    """Get YTD running sum report"""
    return analytics.get_ytd_report(year)

@app.get("/finance/analytics/correlation")
def get_correlation_analytics(days: int = 30):
    """Get correlation between health and spending"""
    # Integrate health data here
    data = analytics.get_correlation_analysis(days)
    
    # Fetch Whoop data for the last N days
    cycles = whoop_client.get_cycle_data(limit=days)
    
    # Map health scores to dates
    health_map = {}
    if cycles and isinstance(cycles, list):
        for cycle in cycles:
            # Whoop date format is usually ISO, we need to match date_str
            dt = cycle.get("start")
            if dt:
                date_str = dt.split("T")[0]
                health_map[date_str] = cycle.get("score", {}).get("strain", 0)
    
    # Also fetch recovery
    recovery = whoop_client.get_recovery_data(limit=days)
    recovery_map = {}
    if recovery and isinstance(recovery, list):
        for rec in recovery:
            dt = rec.get("created_at")
            if dt:
                date_str = dt.split("T")[0]
                recovery_map[date_str] = rec.get("score", {}).get("recovery_score", 0)

    # Merge into data
    for item in data["data"]:
        d = item["date"]
        item["health_score"] = health_map.get(d, 0)
        item["recovery"] = recovery_map.get(d, 0)
        
    return data

@app.get("/finance/analytics/wellness-roi")
def get_wellness_roi():
    """Get Return on Health Investment analytics"""
    return analytics.get_wellness_roi()

@app.get("/finance/analytics/unified-score")
def get_unified_score():
    """Get the Health-Wealth unified score"""
    return analytics.get_unified_score()

# Plaid Link Flow Endpoints
from pydantic import BaseModel

class LinkTokenRequest(BaseModel):
    user_id: str

class PublicTokenRequest(BaseModel):
    public_token: str

@app.post("/finance/plaid/create_link_token")
def create_link_token(request: LinkTokenRequest):
    try:
        print(f"DEBUG: Creating link token for {request.user_id}")
        token = banking_client.create_link_token(request.user_id)
        return {"link_token": token}
    except Exception as e:
        print(f"PLAID LINK TOKEN ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/finance/plaid/exchange_public_token")
def exchange_public_token(request: PublicTokenRequest):
    try:
        print(f"DEBUG: Exchanging public token: {request.public_token[:10]}...")
        result = banking_client.exchange_public_token(request.public_token)
        return result
    except Exception as e:
        print(f"PLAID EXCHANGE ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/finance/fidelity/positions")
def get_fidelity_positions(path: str):
    """Path to the local CSV file"""
    return fidelity_client.load_positions(path)

@app.get("/health/whoop/profile")
def get_whoop_profile():
    return whoop_client.get_profile()

@app.get("/health/whoop/auth")
def get_whoop_auth_url():
    return {"url": whoop_client.get_authorization_url()}

@app.get("/health/whoop/cycles")
def get_whoop_cycles(limit: int = 10):
    return whoop_client.get_cycle_data(limit=limit)

@app.get("/health/whoop/latest")
def get_whoop_latest():
    """Aggregate latest stats for the dashboard"""
    cycles = whoop_client.get_cycle_data(limit=1)
    recovery = whoop_client.get_recovery_data(limit=1)
    sleep = whoop_client.get_sleep_data(limit=1)
    
    print(f"WHOOP LATEST - CYCLES: {cycles}")
    print(f"WHOOP LATEST - RECOVERY: {recovery}")
    print(f"WHOOP LATEST - SLEEP: {sleep}")

    # Extract values safely
    strain_score = 0
    if cycles and isinstance(cycles, list) and len(cycles) > 0:
        strain_score = cycles[0].get("score", {}).get("strain", 0)

    recovery_score = 0
    if recovery and isinstance(recovery, list) and len(recovery) > 0:
        recovery_score = recovery[0].get("score", {}).get("recovery_score", 0)

    sleep_score = 0 
    if sleep and isinstance(sleep, list) and len(sleep) > 0:
        s_score = sleep[0].get("score", {})
        sleep_score = s_score.get("sleep_performance_percentage") or s_score.get("performance_percentage", 0)

    return {
        "strain": round(strain_score, 1),
        "recovery": int(recovery_score),
        "sleep": int(sleep_score)
    }

@app.get("/health/whoop/trends")
def get_whoop_trends(limit: int = 14):
    """Fetch health trends over the last N days"""
    cycles = whoop_client.get_cycle_data(limit=limit)
    recovery = whoop_client.get_recovery_data(limit=limit)
    sleep = whoop_client.get_sleep_data(limit=limit)
    
    trend_map = {}
    
    def get_date(record):
        for key in ["start", "created_at", "updated_at"]:
            val = record.get(key)
            if val: return val.split("T")[0]
        return None

    for c in cycles:
        d = get_date(c)
        if d:
            if d not in trend_map: trend_map[d] = {}
            trend_map[d]["strain"] = round(c.get("score", {}).get("strain", 0), 1)
            
    for r in recovery:
        d = get_date(r)
        if d:
            if d not in trend_map: trend_map[d] = {}
            trend_map[d]["recovery"] = int(r.get("score", {}).get("recovery_score", 0))
            
    for s in sleep:
        d = get_date(s)
        if d:
            if d not in trend_map: trend_map[d] = {}
            s_score = s.get("score", {})
            trend_map[d]["sleep"] = int(s_score.get("sleep_performance_percentage") or s_score.get("performance_percentage", 0))
            
    # Convert to sorted list and ensure all keys exist
    sorted_data = []
    for d in sorted(trend_map.keys()):
        point = trend_map[d]
        sorted_data.append({
            "date": d,
            "strain": point.get("strain", 0),
            "recovery": point.get("recovery", 0),
            "sleep": point.get("sleep", 0)
        })
        
    return sorted_data

@app.get("/health/apple/steps")
def get_apple_steps(path: str, limit: int = 100):
    """Path to export.xml"""
    apple_client.export_xml_path = path
    return apple_client.get_steps(limit)
