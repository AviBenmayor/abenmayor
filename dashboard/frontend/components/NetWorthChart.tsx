"use client";
import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

interface NetWorthDataPoint {
    date: string;
    net_worth: number;
    accounts: number;
}

export default function NetWorthChart() {
    const [data, setData] = useState<NetWorthDataPoint[]>([]);
    const [loading, setLoading] = useState(true);
    const [mounted, setMounted] = useState(false);

    useEffect(() => {
        setMounted(true);
        fetch("http://localhost:8000/finance/net-worth-history")
            .then((res) => res.json())
            .then((data) => {
                setData(data);
                setLoading(false);
            })
            .catch((err) => {
                console.error("Error fetching net worth history:", err);
                setLoading(false);
            });
    }, []);

    if (!mounted) return <div className="h-[200px] bg-zinc-50/30 rounded-2xl animate-pulse" />;
    if (loading) {
        return <div className="h-[200px] flex items-center justify-center text-xs text-muted-foreground animate-pulse font-bold uppercase tracking-widest">Loading Market Data...</div>;
    }

    if (data.length === 0) {
        return (
            <div className="h-[200px] flex items-center justify-center text-xs text-muted-foreground italic font-medium px-8 text-center bg-zinc-50 rounded-xl border border-dashed border-zinc-200">
                Connect your accounts to generate net worth history.
            </div>
        );
    }

    const currentNetWorth = data[data.length - 1]?.net_worth || 0;

    return (
        <div>
            <div className="mb-6">
                <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-1 px-1">Global Valuation</p>
                <h3 className="text-3xl font-bold tracking-tighter text-foreground px-1">
                    ${currentNetWorth.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
                    <span className="text-sm font-medium text-muted-foreground ml-2">.{(currentNetWorth % 1).toFixed(2).substring(2)}</span>
                </h3>
            </div>

            <div className="h-[180px] w-full mt-2">
                <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={data} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#F1F5F9" />
                        <XAxis
                            dataKey="date"
                            axisLine={false}
                            tickLine={false}
                            tick={{ fontSize: 10, fill: '#94A3B8', fontWeight: 600 }}
                            tickFormatter={(value) => {
                                const date = new Date(value);
                                return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
                            }}
                            minTickGap={30}
                        />
                        <YAxis
                            axisLine={false}
                            tickLine={false}
                            tick={{ fontSize: 10, fill: '#94A3B8', fontWeight: 600 }}
                            tickFormatter={(value) => `$${(value / 1000).toFixed(0)}k`}
                        />
                        <Tooltip
                            contentStyle={{
                                borderRadius: '12px',
                                border: '1px solid #E0E6EB',
                                boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.05)',
                                padding: '8px 12px'
                            }}
                            itemStyle={{ fontSize: '12px', fontWeight: 'bold' }}
                            labelStyle={{ fontSize: '10px', fontWeight: 'bold', color: '#627084', marginBottom: '4px', textTransform: 'uppercase' }}
                            formatter={(value: any) => [`$${Number(value).toLocaleString()}`, 'Valuation']}
                            labelFormatter={(label) => new Date(label).toDateString()}
                        />
                        <Line
                            type="monotone"
                            dataKey="net_worth"
                            stroke="#F59F0A"
                            strokeWidth={3}
                            dot={false}
                            activeDot={{ r: 6, fill: '#F59F0A', stroke: '#fff', strokeWidth: 3 }}
                            animationDuration={1500}
                        />
                    </LineChart>
                </ResponsiveContainer>
            </div>
        </div>
    );
}
