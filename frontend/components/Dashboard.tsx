'use client';

import React, { useEffect, useState, useMemo, useCallback } from 'react';
import { supabase } from '@/lib/supabaseClient';
import { SignalCard, SignalData } from './SignalCard';
import { Activity, Filter } from 'lucide-react';

export default function Dashboard() {
  const [signals, setSignals] = useState<SignalData[]>([]);
  const [minPWin, setMinPWin] = useState<number>(0);
  const [isConnected, setIsConnected] = useState<boolean>(false);

  // Initial fetch
  useEffect(() => {
    const fetchSignals = async () => {
      const { data, error } = await supabase
        .from('hft_catalogo_estrategias')
        .select('*')
        .order('timestamp_sinal', { ascending: false })
        .limit(50);
      
      if (error) {
        console.error('Error fetching baseline signals:', error);
      } else if (data) {
        setSignals(data as SignalData[]);
      }
    };
    fetchSignals();
  }, []);

  // Realtime subscription
  useEffect(() => {
    const channel = supabase
      .channel('schema-db-changes')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'hft_catalogo_estrategias' },
        (payload) => {
          const newOrUpdatedSignal = payload.new as SignalData;

          if (payload.eventType === 'INSERT') {
            setSignals((prev) => [newOrUpdatedSignal, ...prev].slice(0, 50));
          } else if (payload.eventType === 'UPDATE') {
            // Update existing without duplicating row if timestamp_sinal is the same
            setSignals((prev) =>
              prev.map((s) => (s.timestamp_sinal === newOrUpdatedSignal.timestamp_sinal && s.ativo === newOrUpdatedSignal.ativo) ? newOrUpdatedSignal : s)
            );
          }
        }
      )
      .subscribe((status) => {
        setIsConnected(status === 'SUBSCRIBED');
      });

    return () => {
      supabase.removeChannel(channel);
    };
  }, []);

  const filteredSignals = useMemo(() => {
    return signals.filter((s) => s.p_win_historica >= minPWin / 100);
  }, [signals, minPWin]);

  return (
    <div className="max-w-7xl mx-auto p-6 animate-in fade-in duration-700">
      
      {/* Header Area */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-8 gap-4 border-b border-dark-border pb-6">
        <div>
          <h1 className="text-2xl font-black text-white tracking-tighter flex items-center">
            <Activity className="w-6 h-6 mr-3 text-dark-accent" />
            HFT STATISTICAL ENGINE
          </h1>
          <p className="text-sm text-dark-text mt-1 flex items-center">
            <span className={`w-2 h-2 rounded-full mr-2 ${isConnected ? 'bg-signal-win animate-pulse' : 'bg-signal-loss'}`} />
            {isConnected ? 'LIVE - Websocket Connected' : 'Disconnected'}
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
