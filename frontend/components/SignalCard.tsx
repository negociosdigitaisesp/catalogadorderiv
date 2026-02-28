import React, { memo } from 'react';
import { StatusBadge, SignalStatus } from './StatusBadge';
import { ArrowUpRight, ArrowDownRight, Activity, Zap, Percent } from 'lucide-react';
import { cn } from '@/lib/utils';
import { format } from 'date-fns';

export interface SignalData {
  id: number;
  ativo: string;
  estrategia: string;
  direcao: 'CALL' | 'PUT';
  p_win_historica: number;
  status: SignalStatus;
  timestamp_sinal: number;
  contexto: {
    kelly_sizing?: number;
    ev_calculado?: number;
    z_score_atual?: number;
  };
}

interface SignalCardProps {
  signal: SignalData;
}

export const SignalCard: React.FC<SignalCardProps> = memo(({ signal }) => {
  const isCall = signal.direcao === 'CALL';
  
  const formattedTime = format(new Date(signal.timestamp_sinal * 1000), 'HH:mm:ss');
  
  return (
    <div className="group relative bg-dark-card border border-dark-border rounded-xl p-4 transition-all duration-300 hover:border-dark-border/80 hover:shadow-[0_0_15px_rgba(49,130,206,0.1)] overflow-hidden">
      {/* Subtle glow effect on hover */}
      <div className="absolute inset-0 bg-gradient-to-br from-dark-accent/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none" />
      
      <div className="flex justify-between items-start mb-4">
        <div>
          <h3 className="text-lg font-bold text-white tracking-tight flex items-center gap-2">
            {signal.ativo}
            <span className="text-xs font-medium text-dark-text px-2 py-0.5 bg-dark-bg rounded-md border border-dark-border/50">
              {signal.estrategia}
            </span>
          </h3>
          <p className="text-xs text-dark-text mt-1">{formattedTime}</p>
        </div>
        <StatusBadge status={signal.status} />
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mt-5">
        
        {/* Direção */}
        <div className="flex flex-col">
          <span className="text-[10px] uppercase text-dark-text tracking-wider font-semibold mb-1">Direction</span>
          <div className={cn(
            "flex items-center text-sm font-bold",
            isCall ? 'text-signal-win' : 'text-signal-loss'
          )}>
            {isCall ? <ArrowUpRight className="w-4 h-4 mr-1" /> : <ArrowDownRight className="w-4 h-4 mr-1" />}
            {signal.direcao}
          </div>
        </div>

        {/* P_Win */}
        <div className="flex flex-col">
          <span className="text-[10px] uppercase text-dark-text tracking-wider font-semibold mb-1 flex items-center">
            <Activity className="w-3 h-3 mr-1" /> P_Win
          </span>
          <div className="text-sm font-mono font-bold text-white">
            {(signal.p_win_historica * 100).toFixed(1)}%
          </div>
        </div>

        {/* EV */}
        <div className="flex flex-col">
          <span className="text-[10px] uppercase text-dark-text tracking-wider font-semibold mb-1 flex items-center">
            <Zap className="w-3 h-3 mr-1" /> Exp. Value
          </span>
          <div className={cn(
            "text-sm font-mono font-bold",
            (signal.contexto?.ev_calculado || 0) > 0 ? "text-signal-win" : "text-signal-neutral"
          )}>
            {signal.contexto?.ev_calculado ? `+${signal.contexto.ev_calculado.toFixed(3)}` : 'N/A'}
          </div>
        </div>

        {/* Sizing (Kelly) */}
        <div className="flex flex-col">
          <span className="text-[10px] uppercase text-dark-text tracking-wider font-semibold mb-1 flex items-center">
            <Percent className="w-3 h-3 mr-1" /> Sizing
          </span>
          <div className="text-sm font-mono font-bold text-dark-accent">
            {signal.contexto?.kelly_sizing ? `${(signal.contexto.kelly_sizing * 100).toFixed(2)}%` : 'N/A'}
          </div>
        </div>

      </div>
    </div>
  );
});

SignalCard.displayName = 'SignalCard';
