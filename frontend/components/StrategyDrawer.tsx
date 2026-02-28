import React, { useEffect, useCallback, useState } from 'react';
import { OracleResult } from '../types/discovery';
import { supabase } from '../lib/supabaseClient';

interface StrategyDrawerProps {
  strategy: OracleResult | null;
  onClose: () => void;
}

function pctStr(v: number): string {
  return `${(v * 100).toFixed(2)}%`;
}

function epochToDate(epoch: number): string {
  return new Date(epoch * 1000).toLocaleDateString('pt-BR');
}

export default function StrategyDrawer({ strategy, onClose }: StrategyDrawerProps) {
  const [active, setActive] = useState<boolean>(strategy?.sniper_active ?? false);
  const [updating, setUpdating] = useState<boolean>(false);

  // Sync active state when strategy changes
  useEffect(() => {
    setActive(strategy?.sniper_active ?? false);
  }, [strategy]);

  // Close on ESC key
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  const handleToggleSniper = useCallback(async () => {
    if (!strategy || updating) return;
    setUpdating(true);
    const newVal = !active;
    try {
      await supabase
        .from('hft_quant.oracle_results')
        .update({ sniper_active: newVal })
        .eq('id', strategy.id);
      setActive(newVal);
    } catch (err) {
      console.error('Failed to update sniper_active:', err);
    } finally {
      setUpdating(false);
    }
  }, [strategy, active, updating]);

  const isOpen = strategy !== null;

  return (
    <>
      {/* Backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/60 z-40"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      {/* Drawer panel */}
      <div
        className={`
          fixed top-0 right-0 h-full w-[480px] bg-gray-900 border-l border-gray-800
          z-50 overflow-y-auto transition-transform duration-300 ease-in-out
          ${isOpen ? 'translate-x-0' : 'translate-x-full'}
        `}
      >
        {strategy && (
          <>
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800 bg-gray-950">
              <span className="font-mono font-bold text-gray-100 tracking-wide">
                {strategy.strategy_id}
              </span>
              <button
                onClick={onClose}
                className="text-gray-500 hover:text-gray-200 font-mono text-lg leading-none px-2"
              >
                ✕
              </button>
            </div>

            {/* Content */}
            <div className="flex flex-col gap-0 font-mono text-xs">

              {/* CONTEXTO */}
              <Section title="CONTEXTO">
                {Object.entries(strategy.config_otimizada ?? {}).map(([k, v]) => (
                  <Row key={k} label={k} value={String(v)} />
                ))}
                <Row label="STATUS" value={strategy.status} highlight />
              </Section>

              {/* MÉTRICAS */}
              <Section title="MÉTRICAS">
                <Row label="Win Rate"   value={pctStr(strategy.win_rate)} />
                <Row label="EV Real"    value={strategy.ev_real?.toFixed(6) ?? '—'} />
                <Row label="Edge vs BE" value={pctStr(strategy.edge_vs_be ?? 0)} />
                <Row label="Sharpe"     value={strategy.sharpe?.toFixed(4) ?? '—'} />
                <Row label="p-value"    value={strategy.p_value?.toFixed(6) ?? '—'} />
                <Row label="N amostral" value={String(strategy.n_amostral)} />
                <Row label="Sizing"     value={`${strategy.sizing_override?.toFixed(1) ?? '—'}×`} />
                <Row label="Válida até" value={epochToDate(strategy.valid_until)} />
              </Section>

              {/* ESTRATÉGIA */}
              <Section title="ESTRATÉGIA">
                <Row label="ID"       value={strategy.strategy_id} />
                <Row label="Ativo"    value={strategy.ativo} />
                <Row label="Padrão"   value={strategy.estrategia} />
              </Section>

              {/* AÇÃO — Toggle Sniper */}
              <Section title="AÇÃO">
                <div className="flex gap-3 px-4 py-3">
                  <button
                    onClick={handleToggleSniper}
                    disabled={updating}
                    className={`
                      flex-1 py-2 font-bold rounded text-sm transition-colors
                      ${active
                        ? 'bg-red-900 hover:bg-red-800 text-red-300 border border-red-700'
                        : 'bg-green-900 hover:bg-green-800 text-green-300 border border-green-700'}
                      ${updating ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
                    `}
                  >
                    {updating ? '...' : active ? 'DESATIVAR SNIPER' : 'ATIVAR NO SNIPER'}
                  </button>
                </div>
                <div className="px-4 pb-2 text-gray-600">
                  Estado atual:{' '}
                  <span className={active ? 'text-green-400' : 'text-gray-500'}>
                    {active ? 'SNIPER ATIVO' : 'INATIVO'}
                  </span>
                </div>
              </Section>
            </div>
          </>
        )}
      </div>
    </>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-b border-gray-800">
      <div className="px-5 py-2 bg-gray-950 text-gray-500 text-[10px] tracking-widest uppercase font-bold">
        {title}
      </div>
      {children}
    </div>
  );
}

function Row({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="flex items-center justify-between px-5 py-1.5 hover:bg-gray-800/50">
      <span className="text-gray-500 capitalize">{label}</span>
      <span className={highlight ? 'text-green-400 font-bold' : 'text-gray-200'}>{value}</span>
    </div>
  );
}
