import React, { memo } from 'react';
import { cn } from '@/lib/utils';
import { Activity, ShieldCheck, AlertTriangle, Ban } from 'lucide-react';

export interface OracleRow {
  id: number;
  ativo: string;
  estrategia: string;
  strategy_id: string;
  win_rate: number;
  n_amostral: number;
  // Quantidades reais — adicionadas pelo fix de integridade estatistica
  n_win_1a: number | null;
  n_win_g1: number | null;
  n_win_g2: number | null;
  n_hit:    number | null;
  ev_real: number;
  edge_vs_be: number;
  status: 'APROVADO' | 'CONDICIONAL' | 'REPROVADO';
  // config_otimizada agora e schema de Grade Horaria (nao Z-Score)
  config_otimizada: {
    tipo?:           string;
    hh_mm?:          string;
    dia_nome?:       string;
    direcao?:        string;
    max_gale?:       number;
    variacao?:       string;
    score_30_7?:     number;
    kelly_quarter?:  number;   // FIX: agora enviado pelo writer
    win_1a_rate?:    number;
    win_gale1_rate?: number;
    win_gale2_rate?: number;
    hit_rate?:       number;
  } | null;
  last_update: string;
}

interface OracleTableProps {
  rows: OracleRow[];
  activeAssets: Set<string>;
}

// ── Rating badge ──────────────────────────────────────────────────────────────
const RatingBadge = ({ status }: { status: OracleRow['status'] }) => {
  const map = {
    APROVADO:    { cls: 'bg-signal-win/10 text-signal-win border-signal-win/20',   Icon: ShieldCheck },
    CONDICIONAL: { cls: 'bg-signal-pre/10 text-signal-pre border-signal-pre/20',   Icon: AlertTriangle },
    REPROVADO:   { cls: 'bg-signal-loss/10 text-signal-loss border-signal-loss/20', Icon: Ban },
  };
  const { cls, Icon } = map[status];
  return (
    <span className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider border', cls)}>
      <Icon className="w-3 h-3" />
      {status}
    </span>
  );
};

// ── Edge bar (win_rate vs break_even) ─────────────────────────────────────────
const EdgeBar = ({ pWin, breakEven }: { pWin: number; breakEven: number }) => {
  const be   = breakEven * 100;
  const pw   = pWin * 100;
  const edge = pw - be;
  const isPos = edge >= 0;

  return (
    <div className="flex flex-col gap-0.5 min-w-[100px]">
      <div className="flex justify-between text-[10px] font-mono">
        <span className="text-dark-text">BE {be.toFixed(1)}%</span>
        <span className={isPos ? 'text-signal-win font-bold' : 'text-signal-loss font-bold'}>
          {isPos ? '+' : ''}{edge.toFixed(1)}%
        </span>
      </div>
      <div className="h-1.5 bg-dark-bg rounded-full overflow-hidden relative">
        <div className="absolute h-full bg-dark-border/60" style={{ width: `${be}%` }} />
        <div
          className={cn('absolute h-full rounded-full transition-all duration-500', isPos ? 'bg-signal-win' : 'bg-signal-loss')}
          style={{ width: `${Math.min(pw, 100)}%` }}
        />
      </div>
    </div>
  );
};

// ── N confiabilidade com breakdown de contagens reais ─────────────────────────
const NLabel = ({ n, n1a, ng1, ng2, nHit }: {
  n: number;
  n1a: number | null;
  ng1: number | null;
  ng2: number | null;
  nHit: number | null;
}) => {
  const label = n >= 300 ? { txt: 'Alta', cls: 'text-signal-win' }
              : n >= 100 ? { txt: 'Media', cls: 'text-signal-pre' }
              : n >= 20  ? { txt: 'Fraca', cls: 'text-signal-neutral' }
              :             { txt: '<20',  cls: 'text-signal-loss' };

  const hasBreakdown = n1a !== null && ng1 !== null && ng2 !== null && nHit !== null;

  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-baseline gap-1">
        <span className="font-mono text-white text-sm">{n.toLocaleString()}</span>
        <span className={cn('text-[10px] font-semibold', label.cls)}>{label.txt}</span>
      </div>
      {hasBreakdown && (
        <div className="font-mono text-[9px] text-dark-text/60 leading-tight">
          1a:{n1a} G1:{ng1} G2:{ng2} Hit:{nHit}
        </div>
      )}
    </div>
  );
};

// ── Direcao badge ─────────────────────────────────────────────────────────────
const DirecaoBadge = ({ direcao }: { direcao?: string }) => {
  if (!direcao) return <span className="text-dark-text/30 text-xs">—</span>;
  const isCall = direcao.toUpperCase() === 'CALL';
  return (
    <span className={cn(
      'inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold',
      isCall ? 'bg-signal-win/10 text-signal-win' : 'bg-signal-loss/10 text-signal-loss'
    )}>
      {isCall ? '▲' : '▼'} {direcao}
    </span>
  );
};

// ── Main Table ────────────────────────────────────────────────────────────────
export const OracleTable: React.FC<OracleTableProps> = memo(({ rows, activeAssets }) => {
  if (rows.length === 0) {
    return (
      <div className="py-20 flex flex-col items-center gap-3 text-dark-text/40">
        <Activity className="w-12 h-12 animate-pulse" />
        <p className="font-mono text-sm tracking-widest uppercase">Sem dados para os filtros aplicados</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-dark-border">
      <table className="w-full text-sm text-left">
        <thead>
          <tr className="border-b border-dark-border bg-dark-bg/60">
            {['Ativo', 'ID Estrategia', 'Horario', 'Direcao', 'N Total', 'WR G2', 'Edge vs BE', 'EV', 'Kelly', 'Rating', 'Sniper'].map((h) => (
              <th key={h} className="px-4 py-3 text-[10px] font-bold uppercase tracking-widest text-dark-text whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const isActive  = activeAssets.has(row.ativo);
            const cfg       = row.config_otimizada;
            const kelly     = cfg?.kelly_quarter ?? 0;
            const breakEven = row.win_rate - row.edge_vs_be;

            return (
              <tr
                key={row.id}
                className={cn(
                  'border-b border-dark-border/50 transition-colors duration-150 hover:bg-dark-card/80',
                  isActive && 'bg-signal-win/5'
                )}
              >
                {/* Ativo */}
                <td className="px-4 py-3 font-bold text-white whitespace-nowrap">
                  {row.ativo}
                </td>

                {/* ID Estrategia */}
                <td className="px-4 py-3">
                  <span className="text-[10px] bg-dark-bg border border-dark-border/60 px-2 py-0.5 rounded font-mono text-dark-text tracking-wider">
                    {row.strategy_id ?? row.estrategia}
                  </span>
                </td>

                {/* Horario + Dia */}
                <td className="px-4 py-3 font-mono text-xs text-white whitespace-nowrap">
                  {cfg?.hh_mm ?? '—'}
                  {cfg?.dia_nome && (
                    <span className="ml-1 text-dark-text/50">{cfg.dia_nome}</span>
                  )}
                </td>

                {/* Direcao */}
                <td className="px-4 py-3">
                  <DirecaoBadge direcao={cfg?.direcao} />
                </td>

                {/* N Total com breakdown real */}
                <td className="px-4 py-3">
                  <NLabel
                    n={row.n_amostral}
                    n1a={row.n_win_1a ?? null}
                    ng1={row.n_win_g1 ?? null}
                    ng2={row.n_win_g2 ?? null}
                    nHit={row.n_hit ?? null}
                  />
                </td>

                {/* WR G2 */}
                <td className="px-4 py-3 font-mono font-bold text-white">
                  {(row.win_rate * 100).toFixed(2)}%
                </td>

                {/* Edge vs BE */}
                <td className="px-4 py-3">
                  <EdgeBar pWin={row.win_rate} breakEven={breakEven} />
                </td>

                {/* EV */}
                <td className="px-4 py-3 font-mono">
                  <span className={cn('font-bold', row.ev_real > 0 ? 'text-signal-win' : 'text-signal-loss')}>
                    {row.ev_real > 0 ? '+' : ''}{row.ev_real.toFixed(4)}
                  </span>
                </td>

                {/* Kelly */}
                <td className="px-4 py-3 font-mono text-dark-accent font-bold">
                  {kelly > 0 ? `${(kelly * 100).toFixed(2)}%` : '—'}
                </td>

                {/* Rating */}
                <td className="px-4 py-3">
                  <RatingBadge status={row.status} />
                </td>

                {/* Sniper Active */}
                <td className="px-4 py-3">
                  {isActive ? (
                    <div className="flex items-center gap-1.5 text-signal-win">
                      <span className="w-2 h-2 rounded-full bg-signal-win animate-pulse" />
                      <span className="text-[10px] font-bold uppercase tracking-wider">ATIVO</span>
                    </div>
                  ) : (
                    <span className="text-dark-text/30 text-xs">—</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
});

OracleTable.displayName = 'OracleTable';
