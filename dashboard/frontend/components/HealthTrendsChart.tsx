"use client";
import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";

interface HealthTrendPoint {
    date: string;
    strain?: number;
    recovery?: number;
    sleep?: number;
}

export default function HealthTrendsChart() {
    const [data, setData] = useState<HealthTrendPoint[]>([]);
    const [loading, setLoading] = useState(true);
    const [mounted, setMounted] = useState(false);

    useEffect(() => {
        setMounted(true);
        fetch("http://localhost:8000/health/whoop/trends?limit=14")
            .then(res => res.json())
            .then(json => {
                setData(json);
                setLoading(false);
            })
            .catch(err => {
                console.error("Error fetching health trends:", err);
                setLoading(false);
            });
    }, []);

    if (!mounted) return <div className="mt-8 pt-8 border-t border-border/50 h-[240px] bg-zinc-50/30 rounded-2xl animate-pulse" />;
    if (loading) return <div className="h-[200px] flex items-center justify-center text-xs text-muted-foreground animate-pulse font-bold uppercase tracking-widest">Compiling Health Trends...</div>;

    if (data.length === 0) return (
        <div className="mt-8 pt-8 border-t border-border/50 text-center">
            <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-4">Wellness Trajectory</p>
            <div className="py-12 bg-zinc-50/50 rounded-2xl border border-dashed border-zinc-200">
                <p className="text-xs text-muted-foreground font-medium italic">Trajectory data will appear here after sync.</p>
            </div>
        </div>
    );

    return (
        <div className="mt-8 pt-8 border-t border-border/50 space-y-8">
            {/* Strain Trajectory */}
            <div>
                <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-4">Activity Load (Strain)</p>
                <div className="h-[180px] w-full bg-zinc-50/30 rounded-2xl p-4 border border-border/50">
                    <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#E2E8F0" />
                            <XAxis
                                dataKey="date"
                                axisLine={false}
                                tickLine={false}
                                tick={{ fontSize: 10, fill: '#94A3B8', fontWeight: 600 }}
                                tickFormatter={(v) => {
                                    const d = new Date(v);
                                    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
                                }}
                            />
                            <YAxis
                                axisLine={false}
                                tickLine={false}
                                tick={{ fontSize: 10, fill: '#94A3B8', fontWeight: 600 }}
                                domain={[0, 21]}
                            />
                            <Tooltip
                                contentStyle={{ borderRadius: '12px', border: '1px solid #E0E6EB', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.05)', padding: '8px 12px' }}
                                itemStyle={{ fontSize: '11px', fontWeight: 'bold' }}
                            />
                            <Line
                                type="monotone"
                                dataKey="strain"
                                stroke="#EF4444"
                                strokeWidth={3}
                                dot={{ r: 3, fill: '#EF4444', strokeWidth: 0 }}
                                name="Strain"
                            />
                        </LineChart>
                    </ResponsiveContainer>
                </div>
            </div>

            {/* Readiness Trajectory */}
            <div>
                <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-4">Readiness (Recovery & Sleep)</p>
                <div className="h-[180px] w-full bg-zinc-50/30 rounded-2xl p-4 border border-border/50">
                    <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#E2E8F0" />
                            <XAxis
                                dataKey="date"
                                axisLine={false}
                                tickLine={false}
                                tick={{ fontSize: 10, fill: '#94A3B8', fontWeight: 600 }}
                                tickFormatter={(v) => {
                                    const d = new Date(v);
                                    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
                                }}
                            />
                            <YAxis
                                axisLine={false}
                                tickLine={false}
                                tick={{ fontSize: 10, fill: '#94A3B8', fontWeight: 600 }}
                                domain={[0, 100]}
                            />
                            <Tooltip
                                contentStyle={{ borderRadius: '12px', border: '1px solid #E0E6EB', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.05)', padding: '8px 12px' }}
                                itemStyle={{ fontSize: '11px', fontWeight: 'bold' }}
                            />
                            <Legend iconType="circle" wrapperStyle={{ fontSize: '10px', fontWeight: 'bold', textTransform: 'uppercase', paddingTop: '10px' }} />
                            <Line
                                type="monotone"
                                dataKey="recovery"
                                stroke="#2EB877"
                                strokeWidth={3}
                                dot={false}
                                name="Recovery %"
                            />
                            <Line
                                type="monotone"
                                dataKey="sleep"
                                stroke="#258CF4"
                                strokeWidth={2}
                                dot={false}
                                strokeDasharray="4 4"
                                name="Sleep %"
                            />
                        </LineChart>
                    </ResponsiveContainer>
                </div>
            </div>
        </div>
    );
}
