const API_BASE_URL = "http://localhost:8000";

export async function fetchBankingTransactions(days = 30) {
    const res = await fetch(`${API_BASE_URL}/finance/banking/transactions?days=${days}`);
    if (!res.ok) return [];
    return res.json();
}

export async function fetchWhoopProfile() {
    const res = await fetch(`${API_BASE_URL}/health/whoop/profile`);
    if (!res.ok) return null;
    return res.json();
}

export async function fetchWhoopLatest() {
    const res = await fetch(`${API_BASE_URL}/health/whoop/latest`);
    if (!res.ok) return null;
    return res.json();
}

export async function fetchHealthCheck() {
    try {
        const res = await fetch(`${API_BASE_URL}/health`);
        return res.json();
    } catch (e) {
        return { status: "error" };
    }
}

// Plaid
export async function createLinkToken(userId: string) {
    const res = await fetch(`${API_BASE_URL}/finance/plaid/create_link_token`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId }),
    });
    return res.json();
}

export async function exchangePublicToken(publicToken: string) {
    const res = await fetch(`${API_BASE_URL}/finance/plaid/exchange_public_token`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ public_token: publicToken }),
    });
    return res.json();
}
export async function fetchUnifiedScore() {
    const res = await fetch(`${API_BASE_URL}/finance/analytics/unified-score`);
    if (!res.ok) return null;
    return res.json();
}

export async function fetchWellnessROI() {
    const res = await fetch(`${API_BASE_URL}/finance/analytics/wellness-roi`);
    if (!res.ok) return null;
    return res.json();
}

export async function fetchHealthCorrelation(days = 14) {
    const res = await fetch(`${API_BASE_URL}/finance/analytics/correlation?days=${days}`);
    if (!res.ok) return { data: [] };
    return res.json();
}
