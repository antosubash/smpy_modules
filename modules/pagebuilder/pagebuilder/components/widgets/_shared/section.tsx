import type { ReactNode } from 'react';
import { cn } from '../../../utils/widgetUtils';

export type SectionVariant = 'default' | 'muted' | 'accent' | 'image-overlay';
export type SectionSpacing = 'compact' | 'default' | 'loose';

export type SectionProps = {
  variant: SectionVariant;
  spacing: SectionSpacing;
  align?: 'left' | 'center';
  as?: 'section' | 'header';
  className?: string;
  children: ReactNode;
} & Omit<React.HTMLAttributes<HTMLElement>, 'className' | 'children'>;

const VARIANT_CLASSES: Record<SectionVariant, string> = {
  default: '',
  muted: 'bg-gray-50 dark:bg-gray-900/40',
  accent: 'bg-primary-800 text-white rounded-xl',
  'image-overlay': 'relative isolate overflow-hidden rounded-xl bg-slate-900 text-white',
};

// Vertical section rhythm is a component-level, tenant-tunable token. A tenant
// (e.g. Mowing) sets `--pb-section-py` to one value so every section shares a
// consistent rhythm; tenants that don't set it keep these per-variant fallbacks
// (the original py-8/12 · py-12/16 · py-16/24 scale), so GCA/Recodo are unchanged.
const SPACING_CLASSES: Record<SectionSpacing, string> = {
  compact: 'py-[var(--pb-section-py,2rem)] lg:py-[var(--pb-section-py,3rem)]',
  default: 'py-[var(--pb-section-py,3rem)] lg:py-[var(--pb-section-py,4rem)]',
  loose: 'py-[var(--pb-section-py,4rem)] lg:py-[var(--pb-section-py,6rem)]',
};

export function Section({
  variant,
  spacing,
  align,
  as = 'section',
  className,
  children,
  ...rest
}: SectionProps) {
  const Tag = as;
  return (
    <Tag
      {...rest}
      className={cn(
        // Same responsive gutters as every other widget container so all
        // sections share one grid edge (px-4 alone left Section content
        // 16px wider than its siblings at lg).
        'container mx-auto px-4 sm:px-6 lg:px-8',
        VARIANT_CLASSES[variant],
        SPACING_CLASSES[spacing],
        align === 'center' && 'text-center',
        className,
      )}
    >
      {children}
    </Tag>
  );
}
