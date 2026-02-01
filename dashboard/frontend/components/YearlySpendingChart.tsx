"use client";
import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Area, AreaChart } from "recharts";

interface YearlyData {
    monthly_spending: {
        [month: number]: number;
    };
    summary: {
        total_spent: number;
        total_budgeted: number;
        average_monthly: number;
        budget_monthly: number;
    };
}

export default function YearlySpendingChart() {
    const [data, setData] = useState<YearlyData | null>(null);
    const [loading, setLoading] = useState(true);
    const [selectedYear, setSelectedYear] = useState(new Date().getFullYear());
    const [mounted, setMounted] = useState(false);

    useEffect(() => {
        setMounted(true);
        fetchYearlyData();
    }, [selectedYear]);

    const fetchYearlyData = async () => {
        try {
            const res = await fetch(`http://localhost:8000/finance/analytics/yearly?year=${selectedYear}`);
            const json = await res.json();
            setData(json);
            setLoading(false);
        } catch (err) {
            console.error("Error fetching yearly data:", err);
            setLoading(false);
        }
    };

    if (!mounted) return <div className="h-[300px] bg-zinc-50/30 rounded-2xl animate-pulse" />;
    if (loading) return <div className="h-[300px] flex items-center justify-center text-xs text-muted-foreground animate-pulse font-bold uppercase tracking-widest">Compiling Annual Trends...</div>;
    if (!data) return <div className="text-sm text-zinc-500 py-8 text-center bg-zinc-50 rounded-xl">No historical data found for this year.</div>;

    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const chartData = months.map((month, idx) => ({
        month,
        spent: data.monthly_spending[idx + 1] || 0,
        budget: data.summary.budget_monthly,
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
                <div className="pr-2">
                    <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Annual Outflow Velocity</p>
                </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
                <div className="p-4 bg-white border border-border rounded-xl">
                    <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-1">Annual Total</p>
                    <p className="text-xl font-bold tracking-tighter">${data.summary.total_spent.toLocaleString(undefined, { maximumFractionDigits: 0 })}</p>
                </div>
                <div className="p-4 bg-white border border-border rounded-xl">
                    <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-1">Monthly Avg</p>
                    <p className="text-xl font-bold tracking-tighter text-[#258CF4]">${data.summary.average_monthly.toLocaleString(undefined, { maximumFractionDigits: 0 })}</p>
                </div>
            </div>

            <div className="h-[300px] w-full mt-4">
                <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                        <defs>
                            <linearGradient id="colorSpentYear" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="5%" stopColor="#F59F0A" stopOpacity={0.1} />
                                <stop offset="95%" stopColor="#F59F0A" stopOpacity={0} />
                            </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#F1F5F9" />
                        <XAxis
                            dataKey="month"
                            axisLine={false}
                            tickLine={false}
                            tick={{ fontSize: 10, fill: '#94A3B8', fontWeight: 600 }}
                        />
                        <YAxis
                            axisLine={false}
                            tickLine={false}
                            tick={{ fontSize: 10, fill: '#94A3B8', fontWeight: 600 }}
                            tickFormatter={(value) => `$${(value / 1000).toFixed(0)}k`}
                        />
                        <Tooltip
                            contentStyle={{ borderRadius: '12px', border: '1px solid #E0E6EB', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.05)', padding: '8px 12px' }}
                            formatter={(value: any) => [`$${Number(value).toLocaleString()}`, 'Outflow']}
                        />
                        <Area
                            type="monotone"
                            dataKey="spent"
                            stroke="#F59F0A"
                            strokeWidth={3}
                            fillOpacity={1}
                            fill="url(#colorSpentYear)"
                            animationDuration={1500}
                        />
                        <Line
                            type="monotone"
                            dataKey="budget"
                            stroke="#CBD5E1"
                            strokeWidth={2}
                            strokeDasharray="4 4"
                            dot={false}
                            name="Budget Baseline"
                        />
                    </AreaChart>
                </ResponsiveContainer>
            </div>
        </div>
    );
}
