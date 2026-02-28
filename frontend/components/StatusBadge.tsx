import React from 'react';
import { cn } from '@/lib/utils';

export type SignalStatus = 'PRE_SIGNAL' | 'CONFIRMED' | 'WIN' | 'LOSS' | 'CANCELED';

interface StatusBadgeProps {
  status: SignalStatus;
  className?: string;
}

const statusConfig: Record<SignalStatus, { label: string; bg: string; text: string; dot: string; border: string }> = {
  PRE_SIGNAL: { label: 'PRE_SIGNAL', bg: 'bg-signal-pre/10', text: 'text-signal-pre', dot: 'bg-signal-pre', border: 'border-signal-pre/20' },
  CONFIRMED: { label: 'CONFIRMED', bg: 'bg-signal-win/10', text: 'text-signal-win', dot: 'bg-signal-win', border: 'border-signal-win/20' },
  WIN: { label: 'WIN', bg: 'bg-signal-win/20', text: 'text-green-400', dot: 'bg-green-400', border: 'border-green-400/30' },
  LOSS: { label: 'LOSS', bg: 'bg-signal-loss/10', text: 'text-signal-loss', dot: 'bg-signal-loss', border: 'border-signal-loss/20' },
  CANCELED: { label: 'CANCELED', bg: 'bg-signal-neutral/10', text: 'text-signal-neutral', dot: 'bg-signal-neutral', border: 'border-signal-neutral/20' },
};

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, className }) => {
  const config = statusConfig[status] || statusConfig.CANCELED;

  return (
    <div
      className={cn(
        'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold uppercase tracking-wider',
        'border',
        config.bg,
        config.text,
        config.border,
        className
      )}
    >
      <span className={cn('w-1.5 h-1.5 rounded-full mr-2', config.dot, status === 'PRE_SIGNAL' && 'animate-pulse')} />
      {config.label}
    </div>
  );
};
