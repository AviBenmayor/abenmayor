"use client";
import { useEffect, useState } from "react";
import { fetchBankingTransactions } from "../lib/api";
import PlaidLinkButton from "./PlaidLinkButton";
import NetWorthChart from "./NetWorthChart";
import MonthlySpendingChart from "./MonthlySpendingChart";
import YearlySpendingChart from "./YearlySpendingChart";
import YTDSummaryChart from "./YTDSummaryChart";

type Tab = "overview" | "monthly" | "yearly" | "ytd";

export default function FinanceWidget() {
    const [data, setData] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [activeTab, setActiveTab] = useState<Tab>("overview");

    useEffect(() => {
        fetchBankingTransactions().then((data) => {
            setData(data);
            setLoading(false);
        });
    }, []);

    return (
        <div className="card-base p-6">
            <div className="flex justify-between items-center mb-8">
                <div className="flex items-center gap-3">
                    <div className="h-10 w-10 rounded-full bg-wealth/10 flex items-center justify-center text-wealth">
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                    </div>
                    <div>
                        <h2 className="text-xl font-bold text-foreground">Wealth</h2>
                        <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Accounts & Spending</p>
                    </div>
                </div>
                <PlaidLinkButton />
            </div>

            {/* Tabs */}
            <div className="flex gap-1 p-1 bg-zinc-100/80 rounded-lg mb-8">
                {["overview", "monthly", "yearly", "ytd"].map((tab) => (
                    <button
                        key={tab}
                        onClick={() => setActiveTab(tab as Tab)}
                        className={`flex-1 px-3 py-1.5 text-xs font-bold rounded-md transition-all ${activeTab === tab
                                ? "bg-white text-foreground shadow-sm"
                                : "text-muted-foreground hover:text-foreground"
                            }`}
                    >
                        {tab.charAt(0).toUpperCase() + tab.slice(1)}
                    </button>
                ))}
            </div>

            {/* Tab Content */}
            {activeTab === "overview" && (
                <div className="space-y-8">
                    {/* Net Worth Graph */}
                    <div>
                        <div className="flex justify-between items-end mb-4 px-1">
                            <h3 className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Net Worth History</h3>
                        </div>
                        <div className="bg-zinc-50/50 rounded-xl p-2 border border-border/50">
                            <NetWorthChart />
                        </div>
                    </div>

                    {/* Recent Transactions */}
                    <div>
                        <h3 className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-4 px-1">Recent Transactions</h3>
                        {loading ? (
                            <div className="space-y-3">
                                {[1, 2, 3].map(i => (
                                    <div key={i} className="h-12 bg-zinc-100 rounded-lg animate-pulse" />
                                ))}
                            </div>
                        ) : (
                            <div className="divide-y divide-zinc-100">
                                {data.length === 0 ? (
                                    <p className="text-muted-foreground italic text-sm py-8 text-center bg-zinc-50 rounded-xl border border-dashed border-zinc-200">No recent activity</p>
                                ) : (
                                    data.slice(0, 5).map((tx, i) => (
                                        <div
                                            key={i}
                                            className="flex justify-between items-center py-3.5 group hover:bg-zinc-50/50 transition-colors px-2 rounded-xl -mx-2"
                                        >
                                            <div className="flex items-center gap-3">
                                                <div className="h-9 w-9 rounded-full bg-zinc-100 flex items-center justify-center text-xs font-bold text-zinc-500 ring-4 ring-white">
                                                    {(tx.name?.[0] || "T").toUpperCase()}
                                                </div>
                                                <div>
                                                    <p className="font-bold text-sm text-foreground">{tx.name || "Transaction"}</p>
                                                    <p className="text-[10px] text-muted-foreground font-bold uppercase tracking-tight">
                                                        {new Date(tx.date).toLocaleDateString('en-US', {
                                                            month: 'short',
                                                            day: 'numeric'
                                                        })}
                                                    </p>
                                                </div>
                                            </div>
                                            <span className={`text-sm font-bold ${tx.amount > 0 ? "text-foreground" : "text-health"}`}>
                                                {tx.amount > 0 ? '-' : '+'}${Math.abs(tx.amount).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                                            </span>
                                        </div>
                                    ))
                                )}
                            </div>
                        )}
                        <button className="w-full py-2.5 mt-6 text-xs font-bold text-muted-foreground border border-border rounded-xl hover:bg-zinc-50 transition-all hover:border-zinc-300">
                            View All Transactions
                        </button>
                    </div>
                </div>
            )}

            {activeTab === "monthly" && <div className="mt-4"><MonthlySpendingChart /></div>}
            {activeTab === "yearly" && <div className="mt-4"><YearlySpendingChart /></div>}
            {activeTab === "ytd" && <div className="mt-4"><YTDSummaryChart /></div>}
        </div>
    );
}
