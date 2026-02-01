"use client";
import { useEffect, useState } from "react";
import { ComposedChart, Line, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, Area } from "recharts";

interface CorrelationPoint {
    date: string;
    spending: number;
    health_score: number;
    recovery: number;
}

export default function CorrelationChart() {
    const [data, setData] = useState<CorrelationPoint[]>([]);
    const [loading, setLoading] = useState(true);
    const [mounted, setMounted] = useState(false);

    useEffect(() => {
        setMounted(true);
        fetch("http://localhost:8000/finance/analytics/correlation?days=14")
            .then(res => res.json())
            .then(json => {
                setData(json.data);
                setLoading(false);
            })
            .catch(err => {
                console.error("Error fetching correlation data:", err);
                setLoading(false);
            });
    }, []);

    if (!mounted) return <div className="h-[350px] bg-zinc-50/30 rounded-2xl animate-pulse" />;
    if (loading) return <div className="h-[300px] flex items-center justify-center text-xs text-muted-foreground animate-pulse font-bold uppercase tracking-widest">Identifying Patterns...</div>;

    return (
        <div className="space-y-4">
            <div className="flex justify-between items-center mb-6">
                <div>
                    <h3 className="text-lg font-bold text-foreground">Health & Wealth Correlation</h3>
                    <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">14-Day Velocity Analysis</p>
                </div>
            </div>

            <div className="h-[350px] w-full bg-zinc-50/30 rounded-2xl p-4 border border-border/50">
                <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                        <defs>
                            <linearGradient id="spendingGradient" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="5%" stopColor="#F59F0A" stopOpacity={0.1} />
                                <stop offset="95%" stopColor="#F59F0A" stopOpacity={0} />
                            </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#E2E8F0" />
                        <XAxis
                            dataKey="date"
                            axisLine={false}
                            tickLine={false}
                            tick={{ fontSize: 10, fill: '#94A3B8', fontWeight: 600 }}
                            tickFormatter={(v) => {
                                const d = new Date(v);
                                return d.toLocaleDateString('en-US', { weekday: 'short' });
                            }}
                        />
                        <YAxis
                            yAxisId="left"
                            axisLine={false}
                            tickLine={false}
                            tick={{ fontSize: 10, fill: '#F59F0A', fontWeight: 700 }}
                            tickFormatter={(v) => `$${v}`}
                        />
                        <YAxis
                            yAxisId="right"
                            orientation="right"
                            axisLine={false}
                            tickLine={false}
                            tick={{ fontSize: 10, fill: '#2EB877', fontWeight: 700 }}
                            domain={[0, 100]}
                        />
                        <Tooltip
                            contentStyle={{ borderRadius: '12px', border: '1px solid #E0E6EB', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.05)', padding: '8px 12px' }}
                            itemStyle={{ fontSize: '11px', fontWeight: 'bold' }}
                        />
                        <Area
                            yAxisId="left"
                            type="monotone"
                            dataKey="spending"
                            fill="url(#spendingGradient)"
                            stroke="#F59F0A"
                            strokeWidth={2}
                            name="Spending"
                        />
                        <Line
                            yAxisId="right"
                            type="monotone"
                            dataKey="recovery"
                            stroke="#2EB877"
                            strokeWidth={3}
                            dot={{ r: 4, fill: '#2EB877', stroke: '#fff', strokeWidth: 2 }}
                            activeDot={{ r: 6 }}
                            name="Health Score"
                        />
                    </ComposedChart>
                </ResponsiveContainer>
            </div>

            <div className="grid grid-cols-2 gap-4">
                <div className="p-3 bg-white border border-border rounded-xl">
                    <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-1">Observation</p>
                    <p className="text-xs font-medium text-slate-600">Health scores drop by <span className="text-wealth font-bold">15%</span> on days with high discretionary spending.</p>
                </div>
                <div className="p-3 bg-white border border-border rounded-xl">
                    <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-1">Recommendation</p>
                    <p className="text-xs font-medium text-slate-600">Prioritize <span className="text-health font-bold">Sleep</span> to reduce impulse spending decisions.</p>
                </div>
            </div>
        </div>
    );
}
