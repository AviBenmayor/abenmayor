"use client";
import { useEffect, useState } from "react";
import { fetchHealthCheck, fetchWhoopProfile, fetchWhoopLatest } from "../lib/api";
import ScoreCircle from "./ScoreCircle";
import HealthTrendsChart from "./HealthTrendsChart";

export default function HealthWidget() {
    const [status, setStatus] = useState("checking");
    const [profile, setProfile] = useState<any>(null);
    const [stats, setStats] = useState<any>(null);

    useEffect(() => {
        fetchHealthCheck().then((res) => setStatus(res.status));
        fetchWhoopProfile().then((res) => {
            if (res && res.first_name) setProfile(res);
        });
        fetchWhoopLatest().then(setStats);
    }, []);

    // Helper to determine recovery color
    const getRecoveryColor = (score: number) => {
        if (score >= 67) return "green";
        if (score >= 34) return "yellow";
        return "red";
    };

    return (
        <div className="card-base p-6">
            <div className="flex justify-between items-center mb-8">
                <div className="flex items-center gap-3">
                    <div className="h-10 w-10 rounded-full bg-health/10 flex items-center justify-center text-health">
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z"></path></svg>
                    </div>
                    <div>
                        <h2 className="text-xl font-bold text-foreground">Health</h2>
                        <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Vitals & Activity</p>
                    </div>
                </div>

                <div className="flex items-center gap-2 px-2 py-1 bg-zinc-50 rounded-full border border-border/50">
                    <span className={`w-1.5 h-1.5 rounded-full ${status === 'healthy' ? 'bg-health shadow-[0_0_8px_rgba(46,184,119,0.5)]' : 'bg-red-500'}`}></span>
                    <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-tighter">Live API</span>
                </div>
            </div>

            {!profile ? (
                <div className="text-center py-12 bg-zinc-50/50 rounded-2xl border border-dashed border-zinc-200">
                    <div className="w-12 h-12 bg-zinc-100 rounded-full flex items-center justify-center mx-auto mb-4">
                        <svg className="w-6 h-6 text-zinc-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.826L10.242 9.172a4 4 0 015.656 0l4 4a4 4 0 01-5.656 5.656l-1.101-1.101m1.928-1.928l-3.357-3.357m-1 1l-2.273 2.273"></path></svg>
                    </div>
                    <p className="mb-6 text-sm text-muted-foreground font-medium">Connect your WHOOP to track vitals</p>
                    <a href="http://localhost:8000/health/whoop/auth" className="px-6 py-2.5 bg-foreground text-white rounded-xl font-bold text-xs transition-all hover:scale-[1.02] hover:shadow-lg inline-block">
                        Connect Account
                    </a>
                </div>
            ) : (
                <div className="space-y-8">
                    <div className="flex justify-around items-center py-4 px-2 bg-zinc-50/50 rounded-2xl border border-border/50">
                        <ScoreCircle
                            label="Recovery"
                            score={stats?.recovery || 0}
                            color={getRecoveryColor(stats?.recovery || 0)}
                        />
                        <div className="w-px h-12 bg-border/50" />
                        <ScoreCircle
                            label="Strain"
                            score={stats?.strain || 0}
                            color="blue"
                        />
                        <div className="w-px h-12 bg-border/50" />
                        <ScoreCircle
                            label="Sleep"
                            score={stats?.sleep || 0}
                            color="blue"
                        />
                    </div>

                    <HealthTrendsChart />

                    <div className="flex items-center gap-4 p-4 bg-white border border-border rounded-xl">
                        <div className="h-10 w-10 rounded-full bg-zinc-100 flex items-center justify-center text-xs font-bold text-zinc-500 overflow-hidden">
                            <img src="/placeholder-user.jpg" alt="Profile" className="w-full h-full object-cover hidden" />
                            {profile.first_name?.[0]}{profile.last_name?.[0]}
                        </div>
                        <div>
                            <p className="text-sm font-bold text-foreground">{profile.first_name} {profile.last_name}</p>
                            <p className="text-[10px] text-muted-foreground font-bold uppercase tracking-wider">WHOOP Pro Member</p>
                        </div>
                        <div className="ml-auto">
                            <span className="px-2 py-1 bg-health/10 text-health text-[10px] font-bold rounded-md">SYNCED</span>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
