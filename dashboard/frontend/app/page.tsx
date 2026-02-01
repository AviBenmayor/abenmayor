"use client";
import { useEffect, useState } from "react";
import FinanceWidget from "../components/FinanceWidget";
import HealthWidget from "../components/HealthWidget";
import CorrelationChart from "../components/CorrelationChart";
import ROIModule from "../components/ROIModule";
import { fetchUnifiedScore } from "../lib/api";

export default function Home() {
  const [unifiedScore, setUnifiedScore] = useState<any>(null);

  useEffect(() => {
    fetchUnifiedScore().then(setUnifiedScore);
  }, []);

  return (
    <div className="relative min-h-screen font-sans selection:bg-blue-100">
      <div className="ambient-bg" />

      <main className="max-w-7xl mx-auto px-6 py-8 md:py-12">
        {/* New Header Section */}
        <header className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-12">
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-foreground">Dashboard</h1>
            <p className="text-muted-foreground mt-1 text-sm font-medium">Global Health & Wealth Overview</p>
          </div>

          <div className="flex items-center gap-6">
            {unifiedScore && (
              <div className="flex flex-col items-end pr-6 border-r border-border hidden sm:flex">
                <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-1">Health-Wealth Score</p>
                <div className="flex items-baseline gap-1">
                  <span className="text-2xl font-bold text-foreground">{unifiedScore.unified_score}</span>
                  <span className="text-xs font-bold text-muted-foreground">/ 100</span>
                </div>
              </div>
            )}
            <div className="flex items-center gap-4">
              <div className="h-10 w-10 flex items-center justify-center bg-white border border-border rounded-full cursor-pointer hover:bg-zinc-50 transition-colors">
                <svg className="w-5 h-5 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"></path></svg>
              </div>
              <div className="h-10 w-10 bg-gradient-to-br from-blue-500 to-purple-500 rounded-full flex items-center justify-center text-white font-bold text-sm shadow-sm hover:scale-105 transition-transform cursor-pointer">
                AB
              </div>
            </div>
          </div>
        </header>

        {/* Health & Wealth Summary "Insights" Section */}
        <section className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-12">
          <div className="p-6 rounded-2xl bg-white border border-border shadow-sm relative overflow-hidden group hover:border-[#2EB877]/30 transition-all">
            <div className="relative z-10">
              <span className="inline-flex items-center px-3 py-1 rounded-full bg-[#2EB877]/10 text-[#2EB877] text-[10px] font-bold uppercase tracking-wider mb-4">
                HEALTH SYNERGY
              </span>
              <h3 className="text-xl font-bold mb-2 text-[#14181F]">Operational Capacity</h3>
              <p className="text-slate-500 text-sm max-w-[320px]">Your average recovery is <span className="text-[#2EB877] font-bold">78%</span>. Pattern indicates high readiness for metabolic optimization.</p>
            </div>
            <div className="absolute top-[-20px] right-[-20px] h-32 w-32 bg-[#2EB877]/5 rounded-full blur-3xl group-hover:bg-[#2EB877]/10 transition-all duration-700" />
          </div>

          <div className="p-6 rounded-2xl bg-white border border-border shadow-sm relative overflow-hidden group hover:border-[#F59F0A]/30 transition-all">
            <div className="relative z-10">
              <span className="inline-flex items-center px-3 py-1 rounded-full bg-[#F59F0A]/10 text-[#F59F0A] text-[10px] font-bold uppercase tracking-wider mb-4">
                WEALTH VELOCITY
              </span>
              <h3 className="text-xl font-bold mb-2 text-[#14181F]">Capital Efficiency</h3>
              <p className="text-slate-500 text-sm max-w-[320px]">Savings rate at <span className="text-[#F59F0A] font-bold">34.2%</span>. Correlating higher sleep quality with reduced impulse spending.</p>
            </div>
            <div className="absolute top-[-20px] right-[-20px] h-32 w-32 bg-[#F59F0A]/5 rounded-full blur-3xl group-hover:bg-[#F59F0A]/10 transition-all duration-700" />
          </div>
        </section>

        {/* Main Widgets Container */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 items-start mb-12">
          <FinanceWidget />
          <HealthWidget />
        </div>

        {/* Advanced Correlation Tier */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 items-stretch">
          <div className="lg:col-span-2 card-base p-6 md:p-8">
            <CorrelationChart />
          </div>
          <div className="card-base p-6 md:p-8">
            <ROIModule />
          </div>
        </div>
      </main>
    </div>
  );
}
