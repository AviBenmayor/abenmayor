"use client";
import { useEffect, useState } from "react";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, Line } from "recharts";

interface YTDData {
    year: number;
    running_data: {
        month: number;
        spent: number;
        total_outflow: number;
        budget: number;
        savings: number;
        investments: number;
        cumulative_spent: number;
        cumulative_outflow: number;
        cumulative_budget: number;
        cumulative_savings: number;
        cumulative_investments: number;
    }[];
    summary: {
        total_spent: number;
        total_outflow: number;
        total_budget: number;
        total_savings: number;
        total_investments: number;
        save_rate: number;
        investment_rate: number;
    };
}

export default function YTDSummaryChart() {
    const [data, setData] = useState<YTDData | null>(null);
    const [loading, setLoading] = useState(true);
    const [selectedYear, setSelectedYear] = useState(new Date().getFullYear());
    const [mounted, setMounted] = useState(false);

    useEffect(() => {
        setMounted(true);
        fetchYTDData();
    }, [selectedYear]);

    const fetchYTDData = async () => {
        try {
            const res = await fetch(`http://localhost:8000/finance/analytics/ytd?year=${selectedYear}`);
            const json = await res.json();
            setData(json);
            setLoading(false);
        } catch (err) {
            console.error("Error fetching YTD data:", err);
            setLoading(false);
        }
    };

    if (!mounted) return <div className="h-[400px] bg-zinc-50/30 rounded-2xl animate-pulse" />;
    if (loading) return <div className="h-[400px] flex items-center justify-center text-xs text-muted-foreground animate-pulse font-bold uppercase tracking-widest">Calculating Cumulative Ratios...</div>;
    if (!data) return <div className="text-sm text-zinc-500 py-8 text-center bg-zinc-50 rounded-xl">No cumulative data available.</div>;

    const monthsArr = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const chartData = data.running_data.map(item => ({
        name: monthsArr[item.month - 1],
        Expenses: item.cumulative_spent,
        TotalOutflow: item.cumulative_outflow,
        Budget: item.cumulative_budget,
        Savings: item.cumulative_savings,
        Investments: item.cumulative_investments,
    }));

    return (
        <div className="space-y-6">
            <div className="flex justify-between items-center bg-zinc-50/50 p-2 rounded-xl border border-border/50">
                <select
                    value={selectedYear}
                    onChange={(e) => setSelectedYear(parseInt(e.target.value))}
                    className="px-3 py-1.5 border border-border rounded-lg bg-white text-xs font-bold focus:outline-none focus:ring-2 focus:ring-wealth/20 transition-all"
                >
                    {[2023, 2024, 2025].map(year => (
                        <option key={year} value={year}>{year}</option>
                    ))}
                </select>
                <div className="flex gap-6 pr-2">
                    <div className="text-right">
                        <p className="text-[10px] text-muted-foreground font-bold uppercase tracking-widest">Efficiency</p>
                        <p className="text-sm font-bold text-health">{data.summary.save_rate.toFixed(1)}%</p>
                    </div>
                    <div className="text-right">
                        <p className="text-[10px] text-muted-foreground font-bold uppercase tracking-widest">Allocation</p>
                        <p className="text-sm font-bold text-[#258CF4]">{data.summary.investment_rate.toFixed(1)}%</p>
                    </div>
                </div>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="p-4 bg-white border border-border rounded-xl">
                    <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-1">YTD Flow</p>
                    <p className="text-xl font-bold tracking-tighter">${data.summary.total_spent.toLocaleString()}</p>
                </div>
                <div className="p-4 bg-white border border-border rounded-xl">
                    <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-1">Target</p>
                    <p className="text-xl font-bold tracking-tighter text-muted-foreground/60">${data.summary.total_budget.toLocaleString()}</p>
                </div>
                <div className="p-4 bg-white border border-border rounded-xl">
                    <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-1">Retained</p>
                    <p className="text-xl font-bold tracking-tighter text-health">${data.summary.total_savings.toLocaleString()}</p>
                </div>
                <div className="p-4 bg-white border border-border rounded-xl">
                    <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-1">Committed</p>
                    <p className="text-xl font-bold tracking-tighter text-[#258CF4]">${data.summary.total_investments.toLocaleString()}</p>
                </div>
            </div>

            <div className="h-[400px] w-full mt-4 bg-zinc-50/30 rounded-2xl p-4 border border-border/50">
                <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                        <defs>
                            <linearGradient id="ytdSpent" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="5%" stopColor="#F59F0A" stopOpacity={0.1} />
                                <stop offset="95%" stopColor="#F59F0A" stopOpacity={0} />
                            </linearGradient>
                            <linearGradient id="ytdSavings" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="5%" stopColor="#2EB877" stopOpacity={0.1} />
                                <stop offset="95%" stopColor="#2EB877" stopOpacity={0} />
                            </linearGradient>
                            <linearGradient id="ytdInvest" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="5%" stopColor="#258CF4" stopOpacity={0.1} />
                                <stop offset="95%" stopColor="#258CF4" stopOpacity={0} />
                            </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#E2E8F0" />
                        <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#94A3B8', fontWeight: 600 }} />
                        <YAxis
                            axisLine={false}
                            tickLine={false}
                            tick={{ fontSize: 10, fill: '#94A3B8', fontWeight: 600 }}
                            tickFormatter={(value) => `$${value >= 1000 ? (value / 1000).toFixed(0) + 'k' : value}`}
                        />
                        <Tooltip
                            contentStyle={{ borderRadius: '12px', border: '1px solid #E0E6EB', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.05)', padding: '8px 12px' }}
                            formatter={(value: any) => [`$${Number(value).toLocaleString()}`, '']}
                        />
                        <Area
                            type="monotone"
                            dataKey="Expenses"
                            stroke="#F59F0A"
                            strokeWidth={3}
                            fillOpacity={1}
                            fill="url(#ytdSpent)"
                        />
                        <Area
                            type="monotone"
                            dataKey="Savings"
                            stroke="#2EB877"
                            strokeWidth={2}
                            fillOpacity={1}
                            fill="url(#ytdSavings)"
                        />
                        <Area
                            type="monotone"
                            dataKey="Investments"
                            stroke="#258CF4"
                            strokeWidth={2}
                            fillOpacity={1}
                            fill="url(#ytdInvest)"
                        />
                        <Line
                            type="monotone"
                            dataKey="Budget"
                            stroke="#CBD5E1"
                            strokeWidth={2}
                            strokeDasharray="6 6"
                            dot={false}
                        />
                    </AreaChart>
                </ResponsiveContainer>
            </div>
        </div>
    );
}
