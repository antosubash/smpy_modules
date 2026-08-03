import { cn } from '../../../utils/widgetUtils';
import { renderRichText } from '../_internal/rich-text';

export type EyebrowTone = 'primary' | 'muted' | 'inverse';

export type EyebrowTextProps = {
  children: string;
  tone?: EyebrowTone;
};

const TONE_CLASSES: Record<EyebrowTone, string> = {
  primary: 'text-primary-800',
  muted: 'text-gray-500 dark:text-gray-400',
  inverse: 'text-white/85',
};

export function EyebrowText({ children, tone = 'primary' }: EyebrowTextProps) {
  // Tolerate undefined at runtime: legacy Puck JSON saved before the eyebrow
  // field existed renders without that prop, and Puck doesn't always merge
  // defaultProps for newly added fields.
  if (!children || children.trim() === '') return null;
  return (
    <p className={cn('text-sm font-semibold uppercase tracking-wider', TONE_CLASSES[tone])}>
      {renderRichText(children)}
    </p>
  );
}
