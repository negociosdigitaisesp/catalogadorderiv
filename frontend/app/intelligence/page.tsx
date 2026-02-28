'use client';

import React, { useEffect, useState, useMemo } from 'react';
import { supabase } from '@/lib/supabaseClient';
import { OracleTable, OracleRow } from '@/components/OracleTable';
import { Database, SlidersHorizontal, Search, RefreshCw } from 'lucide-react';
import { cn } from '@/lib/utils';

const RATINGS = ['Todos', 'APROVADO', 'CONDICIONAL', 'REPROVADO'] as const;
type RatingFilter = typeof RATINGS[number];

export default function IntelligencePage() {
  const [rows, setRows]               = useState<OracleRow[]>([]);
  const [config, setConfig]           = useState<Record<string, unknown>>({});
  const [loading, setLoading]         = useState(true);
  const [lastUpdate, setLastUpdate]   = useState<string>('—');

  // Filters
  const [searchAsset, setSearchAsset] = useState('');
  const [minPWin, setMinPWin]         = useState(0);
  const [ratingFilter, setRatingFilter] = useState<RatingFilter>('Todos');

  // Fetch oracle results
  const fetchData = async () => {
    setLoading(true);
    const { data, error } = await supabase
      .from('hft_oracle_results')
      .select('*')
      .order('ev_real', { ascending: false });

    if (!error && data) {
      setRows(data as OracleRow[]);
      setLastUpdate(new Date().toLocaleTimeString('pt-BR'));
    }
    setLoading(false);
  };

  // Fetch active config.json assets via a Supabase Function or env
  // Here we fetch from hft_oracle_results with rating != REPROVADO as proxy
  const activeAssets = useMemo<Set<string>>(() => {
    return new Set(
      rows
        .filter((r) => r.status !== 'REPROVADO' && r.ev_real > 0)
        .map((r) => r.ativo)
    );
  }, [rows]);

  useEffect(() => {
    fetchData();
  }, []);

  // Filtered results
  const filtered = useMemo(() => {
    return rows.filter((r) => {
      const matchAsset  = searchAsset === '' || r.ativo.toLowerCase().includes(searchAsset.toLowerCase());
      const matchPWin   = r.win_rate * 100 >= minPWin;
      const matchRating = ratingFilter === 'Todos' || r.status === ratingFilter;
      return matchAsset && matchPWin && matchRating;
    });
  }, [rows, searchAsset, minPWin, ratingFilter]);

  // Stats
  const stats = useMemo(() => ({
    total:      rows.length,
    aprovados:  rows.filter((r) => r.status === 'APROVADO').length,
    condicionais: rows.filter((r) => r.status === 'CONDICIONAL').length,
    reprovados: rows.filter((r) => r.status === 'REPROVADO').length,
    avgEV:      rows.length > 0 ? rows.reduce((s, r) => s + r.ev_real, 0) / rows.length : 0,
  }), [rows]);

  return (
    <div className="max-w-[1600px] mx-auto p-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-8 gap-4 border-b border-dark-border pb-6">
        <div>
          <h1 className="text-2xl font-black text-white tracking-tighter flex items-center gap-3">
            <Database className="w-6 h-6 text-dark-accent" />
            ORACLE INTELLIGENCE
          </h1>
          <p className="text-sm text-dark-text mt-1">
            Resultados do backtest · Última atualização: <span className="text-white font-mono">{lastUpdate}</span>
          </p>
        </div>
        <button
          onClick={fetchData}
          className="flex items-center gap-2 px-4 py-2 bg-dark-card border border-dark-border rounded-lg text-sm text-dark-text hover:text-white hover:border-dark-accent transition-all duration-200"
        >
          <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin')} />
          Atualizar
        </button>
      </div>

      {/* Stats Bar */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-8">
        {[
          { label: 'Total',       value: stats.total,       cls: 'text-white' },
          { label: 'Aprovados',   value: stats.aprovados,   cls: 'text-signal-win' },
          { label: 'Condicionais',value: stats.condicionais,cls: 'text-signal-pre' },
          { label: 'Reprovados',  value: stats.reprovados,  cls: 'text-signal-loss' },
          { label: 'EV Médio',    value: stats.avgEV.toFixed(4), cls: stats.avgEV > 0 ? 'text-signal-win' : 'text-signal-loss' },
        ].map(({ label, value, cls }) => (
          <div key={label} className="bg-dark-card border border-dark-border rounded-xl px-4 py-3">
            <p className="text-[10px] uppercase font-semibold text-dark-text tracking-wider mb-1">{label}</p>
            <p className={cn('text-2xl font-black font-mono', cls)}>{value}</p>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3 mb-6 p-4 bg-dark-card border border-dark-border rounded-xl">
        <SlidersHorizontal className="w-4 h-4 text-dark-text flex-shrink-0" />

        {/* Search by asset */}
        <div className="relative flex-shrink-0">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-dark-text" />
          <input
            type="text"
            placeholder="Filtrar ativo..."
            value={searchAsset}
            onChange={(e) => setSearchAsset(e.target.value)}
            className="pl-8 pr-3 py-1.5 bg-dark-bg border border-dark-border rounded-lg text-sm text-white placeholder-dark-text/50 outline-none focus:border-dark-accent transition-colors w-44"
          />
        </div>

        {/* Rating filter */}
        <div className="flex gap-1">
          {RATINGS.map((r) => (
            <button
              key={r}
              onClick={() => setRatingFilter(r)}
              className={cn(
                'px-3 py-1.5 rounded-lg text-xs font-bold uppercase tracking-wider transition-all duration-150 border',
                ratingFilter === r
                  ? r === 'APROVADO'    ? 'bg-signal-win/20 text-signal-win border-signal-win/40'
                  : r === 'CONDICIONAL' ? 'bg-signal-pre/20 text-signal-pre border-signal-pre/40'
                  : r === 'REPROVADO'   ? 'bg-signal-loss/20 text-signal-loss border-signal-loss/40'
                  :                      'bg-dark-accent/20 text-dark-accent border-dark-accent/40'
                  : 'bg-dark-bg text-dark-text border-dark-border hover:border-dark-text/50'
              )}
            >
              {r}
            </button>
          ))}
        </div>

        {/* P_Win slider */}
        <div className="flex items-center gap-3 ml-auto">
          <span className="text-xs text-dark-text whitespace-nowrap">Min P. Win:</span>
          <input
            type="range"
            min={0}
            max={80}
            step={5}
            value={minPWin}
            onChange={(e) => setMinPWin(Number(e.target.value))}
            className="w-28 accent-blue-500"
          />
          <span className="text-sm font-mono font-bold text-white w-12 text-right">
            {minPWin > 0 ? `>${minPWin}%` : 'Todos'}
          </span>
        </div>
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex items-center justify-center py-20 text-dark-text/50">
          <RefreshCw className="w-6 h-6 animate-spin mr-3" />
          <span className="font-mono text-sm">Carregando dados do Oráculo...</span>
        </div>
      ) : (
        <OracleTable rows={filtered} activeAssets={activeAssets} />
      )}

      <p className="text-xs text-dark-text/30 mt-4 font-mono">
        Exibindo {filtered.length} de {rows.length} resultados · hft_oracle_results
      </p>
    </div>
  );
}
