'use client';

import React, { useState, useMemo } from 'react';
import { SignalCard, SignalData } from './SignalCard';
import { Activity, Filter, ShieldCheck, Lock } from 'lucide-react';
import { useHftExecutionBridge } from '../hooks/useHftExecutionBridge';

export default function Dashboard() {
  const [minPWin, setMinPWin] = useState<number>(0);

  const {
    signals,
    pendingMinutes,
    loading,
  } = useHftExecutionBridge();

  // isConnected é derivado: se o hook carregou sem erro, estamos online
  const isConnected = !loading;

  const filteredSignals = useMemo(() => {
    return (signals as SignalData[]).filter((s) => s.p_win_historica >= minPWin / 100);
  }, [signals, minPWin]);

  const lockedSlots = Array.from(pendingMinutes).sort();

  return (
    <div className="max-w-7xl mx-auto p-6 animate-in fade-in duration-700">

      {/* Header Area */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-6 gap-4 border-b border-dark-border pb-6">
        <div>
          <h1 className="text-2xl font-black text-white tracking-tighter flex items-center">
            <Activity className="w-6 h-6 mr-3 text-dark-accent" />
            HFT STATISTICAL ENGINE
          </h1>
          <p className="text-sm text-dark-text mt-1 flex items-center">
            <span className={`w-2 h-2 rounded-full mr-2 ${isConnected ? 'bg-signal-win animate-pulse' : 'bg-signal-loss'}`} />
            {isConnected ? 'LIVE - Websocket Connected' : 'Connecting...'}
          </p>
        </div>

        {/* Live Filters */}
        <div className="flex items-center gap-3 bg-dark-card border border-dark-border rounded-lg p-2 px-3">
          <Filter className="w-4 h-4 text-dark-text" />
          <span className="text-xs font-semibold text-dark-text uppercase tracking-wide">Min P. Win:</span>
          <select
            className="bg-dark-bg border border-dark-border text-white text-sm rounded-md px-2 py-1 outline-none focus:border-dark-accent transition-colors"
            value={minPWin}
            onChange={(e) => setMinPWin(Number(e.target.value))}
          >
            <option value={0}>All Signals</option>
            <option value={55}>&gt; 55%</option>
            <option value={60}>&gt; 60%</option>
            <option value={65}>&gt; 65%</option>
          </select>
        </div>
      </div>

      {/* Painel do Minuto Soberano */}
      <div className="mb-6 bg-dark-card border border-dark-border rounded-xl p-4">
        <div className="flex items-center gap-2 mb-3">
          <ShieldCheck className="w-4 h-4 text-dark-accent" />
          <span className="text-xs font-bold text-dark-accent uppercase tracking-widest">
            Minuto Soberano
          </span>
          <span className="ml-auto text-xs text-dark-text font-mono">
            {lockedSlots.length === 0 ? 'Nenhum slot ativo' : `${lockedSlots.length} slot(s) em operação`}
          </span>
        </div>

        {lockedSlots.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {lockedSlots.map((slot) => (
              <div
                key={slot}
                className="flex items-center gap-1.5 bg-dark-bg border border-dark-accent/40 rounded-md px-2.5 py-1 animate-pulse"
              >
                <Lock className="w-3 h-3 text-dark-accent" />
                <span className="text-xs font-mono font-bold text-white">{slot}</span>
                <span className="text-[10px] text-dark-accent uppercase tracking-wider">LOCKED</span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-dark-text/40 font-mono tracking-wider">
            -- aguardando próximo sinal --
          </p>
        )}
      </div>

      {/* Signal Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
        {filteredSignals.length > 0 ? (
          filteredSignals.map((signal) => (
            <SignalCard key={signal.id} signal={signal} />
          ))
        ) : (
          <div className="col-span-full py-20 flex flex-col items-center justify-center text-dark-text/50">
            <Activity className="w-12 h-12 mb-4 animate-pulse" />
            <p className="font-mono text-sm tracking-widest uppercase">Waiting for signals...</p>
          </div>
        )}
      </div>

    </div>
  );
}
