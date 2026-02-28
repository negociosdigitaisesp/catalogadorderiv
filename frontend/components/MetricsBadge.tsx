import React from 'react';

type StatusType = 'APROVADO' | 'CONDICIONAL' | 'REPROVADO';

interface MetricsBadgeProps {
  status: StatusType;
  label: string;
  value?: number;
  format?: 'percent' | 'decimal' | 'raw';
}

const STATUS_STYLES: Record<StatusType, string> = {
  APROVADO:    'bg-green-950 border border-green-800 text-green-400',
  CONDICIONAL: 'bg-yellow-950 border border-yellow-800 text-yellow-400',
  REPROVADO:   'bg-red-950 border border-red-800 text-red-400',
};

function formatValue(value: number | undefined, format?: string): string {
  if (value === undefined) return '';
  if (format === 'percent') return `${(value * 100).toFixed(1)}%`;
  if (format === 'decimal') return value.toFixed(4);
  return String(value);
}

export default function MetricsBadge({ status, label, value, format }: MetricsBadgeProps) {
  const styleClass = STATUS_STYLES[status] ?? STATUS_STYLES.REPROVADO;
  const formatted = formatValue(value, format);

  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded font-mono text-xs font-semibold ${styleClass}`}>
      <span className="text-gray-500 uppercase tracking-wider">{label}</span>
      {formatted && <span>{formatted}</span>}
    </span>
  );
}
