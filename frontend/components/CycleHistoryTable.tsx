import React from 'react';
import { AgentCycle } from '../types/discovery';

interface CycleHistoryTableProps {
  cycles: AgentCycle[];
}

function epochToLabel(epoch: number): string {
  const d = new Date(epoch * 1000);
  return d.toLocaleString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default function CycleHistoryTable({ cycles }: CycleHistoryTableProps) {
  if (cycles.length === 0) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-sm p-4 font-mono text-xs text-gray-600">
        Nenhum ciclo registrado ainda.
      </div>
    );
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-sm overflow-hidden">
      {/* Title */}
      <div className="px-4 py-2 bg-gray-950 border-b border-gray-800">
        <span className="font-mono text-[10px] text-gray-500 tracking-widest uppercase font-bold">
          Histórico de Ciclos
        </span>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full font-mono text-xs border-collapse">
          <thead>
            <tr className="border-b border-gray-800">
              {['DATA/HORA', 'HIPOS', 'MINER.', 'APROV.', 'ESCRIT.', 'TEMPO'].map((h) => (
                <th
                  key={h}
                  className="px-3 py-1.5 text-left text-gray-600 text-[10px] tracking-wider font-normal"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {cycles.map((cycle, idx) => (
              <tr
                key={cycle.id}
                className={`border-b border-gray-800/50 transition-colors ${
                  idx === 0
                    ? 'bg-gray-800/70 text-gray-200'
                    : 'text-gray-400 hover:bg-gray-800/30'
                }`}
              >
                <td className="px-3 py-1.5 whitespace-nowrap">{epochToLabel(cycle.started_at)}</td>
                <td className="px-3 py-1.5 text-center">{cycle.hipoteses_geradas}</td>
                <td className="px-3 py-1.5 text-center">{cycle.padroes_minerados}</td>
                <td className="px-3 py-1.5 text-center">
                  <span className={cycle.aprovadas > 0 ? 'text-green-400 font-bold' : 'text-gray-600'}>
                    {cycle.aprovadas}
                  </span>
                </td>
                <td className="px-3 py-1.5 text-center">{cycle.estrategias_escritas}</td>
                <td className="px-3 py-1.5 text-center text-gray-600">
                  {cycle.duration_seconds.toFixed(1)}s
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
