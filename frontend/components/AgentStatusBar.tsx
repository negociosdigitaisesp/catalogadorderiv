import React, { useEffect, useState } from 'react';

interface AgentStatusBarProps {
  lastCycleAt: number | null;
  totalStrategies: number;
  approved: number;
  conditional: number;
}

function formatTimeAgo(epoch: number | null): string {
  if (!epoch) return 'Nunca';
  const diffSec = Math.floor(Date.now() / 1000) - epoch;
  if (diffSec < 60) return `${diffSec}s atrás`;
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}min atrás`;
  return `${Math.floor(diffSec / 3600)}h atrás`;
}

export default function AgentStatusBar({
  lastCycleAt,
  totalStrategies,
  approved,
  conditional,
}: AgentStatusBarProps) {
  const [timeAgo, setTimeAgo] = useState<string>(formatTimeAgo(lastCycleAt));

  useEffect(() => {
    setTimeAgo(formatTimeAgo(lastCycleAt));
    const interval = setInterval(() => {
      setTimeAgo(formatTimeAgo(lastCycleAt));
    }, 15000);
    return () => clearInterval(interval);
  }, [lastCycleAt]);

  return (
    <div className="w-full bg-gray-950 border-b border-gray-800 px-6 py-3 flex items-center justify-between">
      {/* Left: Agent title + status */}
      <div className="flex items-center gap-3">
        <span className="text-gray-300 font-mono font-bold tracking-widest text-sm">
          🤖 AUTO QUANT DISCOVERY
        </span>
        <div className="flex items-center gap-1.5 bg-green-950 border border-green-800 px-2 py-0.5 rounded">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
          </span>
          <span className="text-green-400 font-mono text-xs font-bold">ATIVO</span>
        </div>
      </div>

      {/* Right: stats */}
      <div className="flex items-center gap-6 font-mono text-sm">
        <span className="text-gray-500">
          Último ciclo:{' '}
          <span className="text-gray-300">{timeAgo}</span>
        </span>
        <span className="text-gray-600">│</span>
        <span className="text-gray-500">
          Total:{' '}
          <span className="text-green-400 font-bold">{totalStrategies}</span>
        </span>
        <span className="text-gray-600">│</span>
        <span className="text-gray-500">
          ✅{' '}
          <span className="text-green-400 font-bold">{approved}</span>
        </span>
        <span className="text-gray-500">
          ⚠️{' '}
          <span className="text-yellow-400 font-bold">{conditional}</span>
        </span>
      </div>
    </div>
  );
}
