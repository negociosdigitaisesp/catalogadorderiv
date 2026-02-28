import React, { useState, useMemo, useCallback } from 'react';
import type { NextPage } from 'next';
import Head from 'next/head';
import { OracleResult } from '../types/discovery';
import { useOracleResults } from '../hooks/useOracleResults';
import { useAgentCycles } from '../hooks/useAgentCycles';
import AgentStatusBar from '../components/AgentStatusBar';
import StrategyCard from '../components/StrategyCard';
import StrategyDrawer from '../components/StrategyDrawer';
import CycleHistoryTable from '../components/CycleHistoryTable';

type FilterStatus = 'TODOS' | 'APROVADO' | 'CONDICIONAL';

const ATIVOS = ['TODOS', 'R_10', 'R_25', 'R_50', 'R_75', 'R_100',
  'CRASH_300', 'CRASH_500', 'CRASH_1000', 'BOOM_300', 'BOOM_500', 'BOOM_1000'];
const DIRECOES = ['TODOS', 'CALL', 'PUT'];
const SESSOES  = ['TODOS', 'Asian', 'London', 'Overlap', 'NY'];

const DiscoveryPage: NextPage = () => {
  const { strategies, loading, error, approved, conditional } = useOracleResults();
  const { cycles, lastCycleAt } = useAgentCycles();

  const [selectedStrategy, setSelectedStrategy] = useState<OracleResult | null>(null);
  const [filterStatus, setFilterStatus]         = useState<FilterStatus>('TODOS');
  const [filterAtivo, setFilterAtivo]           = useState<string>('TODOS');
  const [filterDirecao, setFilterDirecao]       = useState<string>('TODOS');
  const [filterSessao, setFilterSessao]         = useState<string>('TODOS');

  const handleSelect = useCallback((s: OracleResult) => setSelectedStrategy(s), []);
  const handleClose  = useCallback(() => setSelectedStrategy(null), []);

  // Filtered + sorted list — no re-render of unrelated components
  const filteredStrategies = useMemo(() => {
    let list = [...strategies];
    if (filterStatus !== 'TODOS') list = list.filter((s) => s.status === filterStatus);
    if (filterAtivo !== 'TODOS')  list = list.filter((s) => s.ativo === filterAtivo);
    if (filterDirecao !== 'TODOS') {
      list = list.filter((s) => {
        const dir = (s.config_otimizada?.direcao as string) ?? '';
        return dir.toUpperCase() === filterDirecao;
      });
    }
    if (filterSessao !== 'TODOS') {
      list = list.filter((s) => {
        const sessao = (s.config_otimizada?.sessao as string) ?? '';
        return sessao === filterSessao;
      });
    }
    // Sort by EV desc
    return list.sort((a, b) => (b.ev_real ?? 0) - (a.ev_real ?? 0));
  }, [strategies, filterStatus, filterAtivo, filterDirecao, filterSessao]);

  // Sidebar stats
  const sideStats = useMemo(() => {
    if (strategies.length === 0) return null;

    const approvedList = strategies.filter((s) => s.status === 'APROVADO');
    const approvalRate = strategies.length > 0
      ? ((approved.length / strategies.length) * 100).toFixed(1)
      : '0.0';

    const bestEV = strategies.reduce((best, s) => Math.max(best, s.ev_real ?? 0), 0);

    const ativoCounts: Record<string, number> = {};
    strategies.forEach((s) => { ativoCounts[s.ativo] = (ativoCounts[s.ativo] ?? 0) + 1; });
    const topAtivo = Object.entries(ativoCounts).sort((a, b) => b[1] - a[1])[0]?.[0] ?? '—';

    const oldestId = [...strategies]
      .sort((a, b) => (a.last_update ?? 0) - (b.last_update ?? 0))[0]?.strategy_id ?? '—';

    return { approvalRate, bestEV, topAtivo, oldestId };
  }, [strategies, approved]);

  return (
    <>
      <Head>
        <title>Auto Quant Discovery | HFT Oracle</title>
        <meta name="description" content="Real-time strategy discovery dashboard" />
      </Head>

      <div className="min-h-screen bg-gray-950 text-gray-300 flex flex-col">

        {/* ── TOP BAR ── */}
        <div className="sticky top-0 z-30">
          <AgentStatusBar
            lastCycleAt={lastCycleAt}
            totalStrategies={strategies.length}
            approved={approved.length}
            conditional={conditional.length}
          />
        </div>

        {/* ── MAIN CONTENT ── */}
        <div className="flex-1 grid grid-cols-3 gap-0 min-h-0">

          {/* ── LEFT (col-span-2): Filters + Cards ── */}
          <div className="col-span-2 border-r border-gray-800 flex flex-col overflow-hidden">

            {/* Filters bar */}
            <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-800 bg-gray-900 flex-wrap">

              {/* Status pills */}
              <div className="flex gap-1 font-mono text-xs">
                {(['TODOS', 'APROVADO', 'CONDICIONAL'] as FilterStatus[]).map((s) => (
                  <button
                    key={s}
                    onClick={() => setFilterStatus(s)}
                    className={`px-3 py-1 rounded-full border transition-colors ${
                      filterStatus === s
                        ? 'bg-gray-700 border-gray-500 text-gray-200'
                        : 'border-gray-800 text-gray-600 hover:border-gray-600 hover:text-gray-400'
                    }`}
                  >
                    {s}
                  </button>
                ))}
              </div>

              <span className="text-gray-700">│</span>

              {/* Selects */}
              {[
                { label: 'Ativo', value: filterAtivo, setter: setFilterAtivo, options: ATIVOS },
                { label: 'Direção', value: filterDirecao, setter: setFilterDirecao, options: DIRECOES },
                { label: 'Sessão', value: filterSessao, setter: setFilterSessao, options: SESSOES },
              ].map(({ label, value, setter, options }) => (
                <select
                  key={label}
                  value={value}
                  onChange={(e) => setter(e.target.value)}
                  className="bg-gray-800 border border-gray-700 text-gray-300 text-xs font-mono px-2 py-1 rounded focus:outline-none focus:border-gray-500"
                >
                  {options.map((o) => (
                    <option key={o} value={o}>{o === 'TODOS' ? `${label} ▼` : o}</option>
                  ))}
                </select>
              ))}

              <span className="ml-auto font-mono text-xs text-gray-600">
                {filteredStrategies.length} estratégia{filteredStrategies.length !== 1 ? 's' : ''}
              </span>
            </div>

            {/* Strategy grid */}
            <div className="flex-1 overflow-y-auto px-4 py-3">
              {loading && (
                <div className="text-center py-20 text-gray-600 font-mono text-sm animate-pulse">
                  Carregando estratégias...
                </div>
              )}
              {error && (
                <div className="text-center py-20 text-red-500 font-mono text-sm">
                  Erro: {error}
                </div>
              )}
              {!loading && !error && filteredStrategies.length === 0 && (
                <div className="flex flex-col items-center justify-center py-24 gap-3 text-gray-700">
                  <span className="text-4xl">📊</span>
                  <p className="font-mono text-sm">Nenhuma estratégia encontrada.</p>
                  <p className="font-mono text-xs">
                    Execute <code className="bg-gray-900 px-1">python agente/core/agent_discovery.py</code> para iniciar um ciclo.
                  </p>
                </div>
              )}
              <div className="flex flex-col gap-2">
                {filteredStrategies.map((strategy) => (
                  <StrategyCard
                    key={strategy.id}
                    strategy={strategy}
                    onSelect={handleSelect}
                    isNew={(strategy as any)._isNew}
                  />
                ))}
              </div>
            </div>
          </div>

          {/* ── RIGHT (col-span-1): History + Stats ── */}
          <div className="col-span-1 overflow-y-auto px-4 py-4 flex flex-col gap-4">

            {/* Cycle history */}
            <CycleHistoryTable cycles={cycles} />

            {/* Summary stats */}
            {sideStats && (
              <div className="bg-gray-900 border border-gray-800 rounded-sm overflow-hidden">
                <div className="px-4 py-2 bg-gray-950 border-b border-gray-800">
                  <span className="font-mono text-[10px] text-gray-500 tracking-widest uppercase font-bold">
                    Resumo Global
                  </span>
                </div>
                <div className="font-mono text-xs">
                  {[
                    { label: 'Taxa de aprovação', value: `${sideStats.approvalRate}%` },
                    { label: 'Melhor EV',          value: sideStats.bestEV.toFixed(4) },
                    { label: 'Ativo top',           value: sideStats.topAtivo },
                    { label: 'Estratégia mais antiga', value: sideStats.oldestId },
                    { label: 'Total aprovadas',     value: String(approved.length), green: true },
                    { label: 'Total condicionais',  value: String(conditional.length) },
                  ].map(({ label, value, green }) => (
                    <div key={label} className="flex justify-between px-4 py-1.5 border-b border-gray-800/50 hover:bg-gray-800/30">
                      <span className="text-gray-500">{label}</span>
                      <span className={green ? 'text-green-400 font-bold' : 'text-gray-200'}>{value}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* SQL reminder card */}
            <div className="bg-gray-900 border border-yellow-900/50 rounded-sm p-3 font-mono text-[10px] text-yellow-700">
              <p className="font-bold text-yellow-600 mb-1">⚠ SQL SUPABASE NECESSÁRIO</p>
              <p>Execute as migrations no editor SQL do Supabase antes de usar esta página. Ver PRD Módulo 6.</p>
            </div>
          </div>
        </div>

        {/* ── STRATEGY DRAWER ── */}
        <StrategyDrawer strategy={selectedStrategy} onClose={handleClose} />
      </div>
    </>
  );
};

export default DiscoveryPage;
