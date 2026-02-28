import React, { useMemo } from 'react';
import { OracleResult } from '../types/discovery';

interface StrategyCardProps {
  strategy: OracleResult & { _isNew?: boolean };
  onSelect: (strategy: OracleResult) => void;
  isNew?: boolean;
}

function epochToDate(epoch: number): string {
  const d = new Date(epoch * 1000);
  return d.toLocaleDateString('pt-BR');
}

function pctStr(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

function edgeStr(v: number): string {
  return `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`;
}

const BORDER_COLORS: Record<string, string> = {
  APROVADO:    'border-l-green-500',
  CONDICIONAL: 'border-l-yellow-500',
  REPROVADO:   'border-l-red-700',
};

const STATUS_TEXT_COLORS: Record<string, string> = {
  APROVADO:    'text-green-400',
  CONDICIONAL: 'text-yellow-400',
  REPROVADO:   'text-red-400',
};

export default function StrategyCard({ strategy, onSelect, isNew }: StrategyCardProps) {
  const borderColor = BORDER_COLORS[strategy.status] ?? 'border-l-gray-600';
  const statusColor = STATUS_TEXT_COLORS[strategy.status] ?? 'text-gray-400';

  const ctx = useMemo(() => {
    const c = strategy.config_otimizada ?? {};
    const sessao = (c.sessao ?? c.session ?? '—') as string;
    const direcao = (c.direcao ?? '—') as string;
    const dia = (c.dia_da_semana ?? '—') as string;
    return { sessao, direcao, dia };
  }, [strategy.config_otimizada]);

  return (
    <div
      onClick={() => onSelect(strategy)}
      className={`
        relative bg-gray-900 border border-gray-800 border-l-4 ${borderColor}
        hover:bg-gray-800 cursor-pointer transition-colors duration-150
        ${isNew ? 'animate-pulse' : ''}
        rounded-sm font-mono text-xs
      `}
    >
      {/* Header row */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-800">
        <span className="text-gray-200 font-bold tracking-wide">{strategy.strategy_id}</span>
        <span className={`font-bold ${statusColor}`}>{strategy.status}</span>
      </div>

      {/* Context row */}
      <div className="flex items-center gap-2 px-3 py-1.5 text-gray-500 border-b border-gray-800">
        <span className="text-gray-300">{strategy.ativo}</span>
        <span>│</span>
        <span>{ctx.direcao}</span>
        <span>│</span>
        <span>{ctx.sessao}</span>
        <span>│</span>
        <span>{ctx.dia}</span>
      </div>

      {/* Metrics row */}
      <div className="grid grid-cols-6 gap-0 px-3 py-2 border-b border-gray-800">
        {[
          { label: 'WIN RATE', value: pctStr(strategy.win_rate) },
          { label: 'EV', value: strategy.ev_real?.toFixed(4) ?? '—' },
          { label: 'EDGE', value: edgeStr(strategy.edge_vs_be ?? 0) },
          { label: 'SHARPE', value: strategy.sharpe?.toFixed(2) ?? '—' },
          { label: 'N', value: String(strategy.n_amostral) },
          { label: 'P-VALUE', value: strategy.p_value?.toFixed(4) ?? '—' },
        ].map(({ label, value }) => (
          <div key={label} className="flex flex-col items-center">
            <span className="text-gray-600 text-[10px] tracking-wider">{label}</span>
            <span className="text-gray-200 font-bold">{value}</span>
          </div>
        ))}
      </div>

      {/* Footer row */}
      <div className="flex items-center gap-4 px-3 py-1.5 text-gray-500">
        <span>
          Kelly: <span className="text-gray-300">{strategy.config_otimizada?.kelly_quarter != null
            ? pctStr(Number(strategy.config_otimizada.kelly_quarter))
            : '—'}</span>
        </span>
        <span>│</span>
        <span>
          Sizing: <span className="text-gray-300">{strategy.sizing_override?.toFixed(1) ?? '—'}x</span>
        </span>
        <span>│</span>
        <span>
          Válida até: <span className="text-gray-300">{epochToDate(strategy.valid_until)}</span>
        </span>
        {strategy.sniper_active && (
          <span className="ml-auto text-green-500 font-bold">● SNIPER ON</span>
        )}
      </div>
    </div>
  );
}
