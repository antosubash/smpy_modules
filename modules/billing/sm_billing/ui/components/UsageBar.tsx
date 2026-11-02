import { cn } from '@simple-module-py/ui/lib/utils';
import type { UsageTone } from '../utils/usage';

const FILL: Record<UsageTone, string> = {
  normal: 'bg-primary',
  warning: 'bg-amber-500',
  over: 'bg-destructive',
};

interface Props {
  percent: number;
  tone: UsageTone;
  label: string;
  className?: string;
}

/**
 * A progress bar whose fill takes the warning colour at 90% and the
 * destructive one at the limit — the ui `Progress` has one fixed colour.
 */
export function UsageBar({ percent, tone, label, className }: Props) {
  const clamped = Math.max(0, Math.min(100, percent));
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(clamped)}
      data-tone={tone}
      className={cn('h-2 w-full overflow-hidden rounded-full bg-muted', className)}
    >
      <div className={cn('h-full transition-all', FILL[tone])} style={{ width: `${clamped}%` }} />
    </div>
  );
}
