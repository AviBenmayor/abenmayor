"use client";
import { useEffect, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, Cell } from "recharts";

interface MonthlyData {
    categories: {
        [category: string]: {
            spent: number;
            budgeted: number;
            remaining: number;
            percent_used: number;
        };
    };
    summary: {
        total_spent: number;
        total_budgeted: number;
        remaining: number;
        percent_used: number;
    };
}

export default function MonthlySpendingChart() {
    const [data, setData] = useState<MonthlyData | null>(null);
    const [loading, setLoading] = useState(true);
    const [selectedMonth, setSelectedMonth] = useState(new Date().getMonth() + 1);
    const [selectedYear, setSelectedYear] = useState(new Date().getFullYear());
    const [mounted, setMounted] = useState(false);

    useEffect(() => {
        setMounted(true);
        fetchMonthlyData();
    }, [selectedMonth, selectedYear]);

    const fetchMonthlyData = async () => {
        try {
            const res = await fetch(`http://localhost:8000/finance/analytics/monthly?year=${selectedYear}&month=${selectedMonth}`);
            const json = await res.json();
            setData(json);
            setLoading(false);
        } catch (err) {
            console.error("Error fetching monthly data:", err);
            setLoading(false);
        }
    };

    if (!mounted) return <div className="h-[300px] bg-zinc-50/30 rounded-2xl animate-pulse" />;
    if (loading) return <div className="h-[300px] flex items-center justify-center text-xs text-muted-foreground animate-pulse font-bold uppercase tracking-widest">Loading Analytics...</div>;
    if (!data) return <div className="text-sm text-zinc-500 py-8 text-center bg-zinc-50 rounded-xl">No distribution data available for this period.</div>;

    const chartData = Object.entries(data.categories)
        .map(([category, values]) => ({
            category,
            spent: values.spent,
            budgeted: values.budgeted,
        }))
        .sort((a, b) => b.spent - a.spent)
        .slice(0, 8);

    const months = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ];

    return (
        <div className="space-y-6">
            {/* Nav & Month Picker */}
            <div className="flex justify-between items-center bg-zinc-50/50 p-2 rounded-xl border border-border/50">
                <div className="flex gap-2">
                    <select
                        value={selectedMonth}
                        onChange={(e) => setSelectedMonth(parseInt(e.target.value))}
                        className="px-3 py-1.5 border border-border rounded-lg bg-white text-xs font-bold focus:outline-none focus:ring-2 focus:ring-wealth/20 transition-all"
                    >
                        {months.map((month, idx) => (
                            <option key={idx} value={idx + 1}>{month}</option>
                        ))}
                    </select>
                    <select
                        value={selectedYear}
                        onChange={(e) => setSelectedYear(parseInt(e.target.value))}
                        className="px-3 py-1.5 border border-border rounded-lg bg-white text-xs font-bold focus:outline-none focus:ring-2 focus:ring-wealth/20 transition-all"
                    >
                        {[2023, 2024, 2025].map(year => (
                            <option key={year} value={year}>{year}</option>
                        ))}
                    </select>
                </div>
                <div className="pr-2">
                    <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Spending Distribution</p>
                </div>
            </div>

            {/* Summary Grid */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div className="p-4 bg-white border border-border rounded-xl">
                    <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-1">Monthly Total</p>
                    <p className="text-xl font-bold tracking-tighter">${data.summary.total_spent.toLocaleString(undefined, { maximumFractionDigits: 0 })}</p>
                </div>
                <div className="p-4 bg-white border border-border rounded-xl">
                    <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-1">Budget Limit</p>
                    <p className="text-xl font-bold tracking-tighter text-muted-foreground/60">${data.summary.total_budgeted.toLocaleString(undefined, { maximumFractionDigits: 0 })}</p>
                </div>
                <div className="p-4 bg-white border border-border rounded-xl">
                    <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-1">Variance</p>
                    <p className={`text-xl font-bold tracking-tighter ${data.summary.remaining >= 0 ? 'text-health' : 'text-[#EF4444]'}`}>
                        {data.summary.remaining >= 0 ? '+' : '-'}${Math.abs(data.summary.remaining).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                    </p>
                </div>
            </div>

            {/* Horizontal Bar Chart */}
            <div className="h-[400px] w-full mt-4">
                <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                        data={chartData}
                        layout="vertical"
                        margin={{ top: 5, right: 30, left: 40, bottom: 5 }}
                        barSize={32}
                    >
                        <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#F1F5F9" />
                        <XAxis type="number" hide />
                        <YAxis
                            dataKey="category"
                            type="category"
                            axisLine={false}
                            tickLine={false}
                            tick={{ fontSize: 11, fontWeight: 700, fill: '#14181F' }}
                            width={120}
                        />
                        <Tooltip
                            cursor={{ fill: '#F8FAFC' }}
                            contentStyle={{ borderRadius: '12px', border: '1px solid #E0E6EB', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.05)', padding: '8px 12px' }}
                            formatter={(value: any) => [`$${Number(value).toLocaleString()}`, '']}
                        />
                        <Bar dataKey="spent" radius={[0, 4, 4, 0]}>
                            {chartData.map((entry, index) => (
                                <Cell key={`cell-${index}`} fill={entry.spent > entry.budgeted ? '#EF4444' : '#F59F0A'} />
                            ))}
                        </Bar>
                        <Bar dataKey="budgeted" fill="#E2E8F0" radius={[0, 4, 4, 0]} barSize={8} />
                    </BarChart>
                </ResponsiveContainer>
            </div>
        </div>
    );
}
