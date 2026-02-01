"use client";
import { useEffect, useState } from "react";

interface Investment {
    name: string;
    amount: number;
    roi: string;
    impact: string;
}

interface ROIData {
    total_invested_ytd: number;
    major_investments: Investment[];
    estimated_savings: number;
}

export default function ROIModule() {
    const [data, setData] = useState<ROIData | null>(null);

    useEffect(() => {
        fetch("http://localhost:8000/finance/analytics/wellness-roi")
            .then(res => res.json())
            .then(setData);
    }, []);

    if (!data) return null;

    return (
        <div className="space-y-6">
            <div className="flex justify-between items-end">
                <div>
                    <h3 className="text-lg font-bold text-foreground">Wellness ROI</h3>
                    <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest text-health">Return on Health Investment</p>
                </div>
                <div className="text-right">
                    <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-1">Total Health Spend (YTD)</p>
                    <p className="text-2xl font-bold tracking-tighter">${data.total_invested_ytd.toLocaleString()}</p>
                </div>
            </div>

            <div className="grid grid-cols-1 gap-3">
                {data.major_investments.map((inv, i) => (
                    <div key={i} className="flex items-center justify-between p-4 bg-white border border-border rounded-xl group hover:border-[#2EB877]/30 transition-all">
                        <div className="flex items-center gap-4">
                            <div className="h-10 w-10 rounded-full bg-zinc-50 flex items-center justify-center text-xs font-bold text-zinc-500 border border-border group-hover:bg-[#2EB877]/10 group-hover:text-health transition-colors">
                                {inv.name[0]}
                            </div>
                            <div>
                                <p className="text-sm font-bold text-foreground">{inv.name}</p>
                                <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-tight">${inv.amount} / month</p>
                            </div>
                        </div>
                        <div className="text-right">
                            <span className="inline-block px-2 py-0.5 rounded-md bg-[#2EB877]/10 text-health text-[10px] font-bold uppercase mb-1">
                                {inv.roi} ROI
                            </span>
                            <p className="text-xs font-bold text-slate-600">{inv.impact}</p>
                        </div>
                    </div>
                ))}
            </div>

            <div className="p-4 bg-gradient-to-br from-[#E7F7EF] to-white border border-[#2EB877]/20 rounded-xl">
                <div className="flex items-start gap-4">
                    <div className="h-8 w-8 rounded-full bg-health flex items-center justify-center text-white text-sm shadow-lg shadow-health/20">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"></path></svg>
                    </div>
                    <div>
                        <p className="text-[10px] font-bold text-health uppercase tracking-widest mb-1">Productivity & Prevention Gain</p>
                        <p className="text-sm font-medium text-slate-700">Estimated value of health improvements: <span className="font-bold text-foreground">${data.estimated_savings.toLocaleString()}</span></p>
                    </div>
                </div>
            </div>
        </div>
    );
}
