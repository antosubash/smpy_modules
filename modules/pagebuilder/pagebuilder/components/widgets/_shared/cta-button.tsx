import { cn } from '../../../utils/widgetUtils';
import { renderRichText } from '../_internal/rich-text';

export type CTAButtonVariant = 'primary' | 'secondary' | 'inverse-primary' | 'inverse-outline';

export type CTAButtonSize = 'md' | 'lg';

export type CTAButtonProps = {
  label: string;
  href: string;
  variant: CTAButtonVariant;
  size?: CTAButtonSize;
};

// Shape and type are tenant-tunable: GCA's design system uses pill buttons
// with SemiBold 17px labels (see `.gca-root` in gca.css); the fallbacks keep
// the original rounded-md / medium / text-base look for other tenants.
const BASE =
  'inline-flex items-center justify-center rounded-[var(--pb-button-radius,0.375rem)] font-[number:var(--pb-button-weight,500)] transition-colors ' +
  'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-500';

// Padding is tenant-tunable alongside the font size so a tenant whose buttons
// are a fixed Figma size (BioGarden: 211x54 at 18px) can hit it without every
// other tenant's buttons changing — the fallbacks are the previous literals.
const SIZE_CLASSES: Record<CTAButtonSize, string> = {
  md: 'py-[var(--pb-button-py-md,0.625rem)] px-[var(--pb-button-px-md,1.25rem)] text-[length:var(--pb-button-font-size-md,0.875rem)]',
  lg: 'py-[var(--pb-button-py,0.75rem)] px-[var(--pb-button-px,1.5rem)] text-[length:var(--pb-button-font-size,1rem)]',
};

// The two "inverse" variants sit on a photo/dark band (Hero, CallToAction).
// Their surface is tokenized because tenants disagree on what a primary
// button on a photo looks like: the default is the solid white pill, while
// BioGarden's Figma draws it as a transparent white-outlined pill. Every
// fallback reproduces the previous hardcoded value, so tenants that set none
// of these tokens render exactly as before.
const VARIANT_CLASSES: Record<CTAButtonVariant, string> = {
  primary: 'bg-primary-800 hover:bg-primary-900 text-white',
  secondary:
    'border border-gray-300 dark:border-gray-700 text-gray-900 dark:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-800',
  'inverse-primary':
    'bg-[var(--pb-button-inverse-bg,#ffffff)] text-[color:var(--pb-button-inverse-fg,var(--color-primary-800))] ' +
    'border-[length:var(--pb-button-inverse-border-width,0px)] border-solid border-[color:var(--pb-button-inverse-border,transparent)] ' +
    'hover:bg-[var(--pb-button-inverse-bg-hover,var(--color-primary-50))]',
  'inverse-outline':
    'bg-[var(--pb-button-outline-bg,rgb(255_255_255/0.2))] border-[length:var(--pb-button-outline-border-width,1px)] border-solid ' +
    'border-[color:var(--pb-button-outline-border,rgb(255_255_255/0.55))] text-white ' +
    'hover:bg-[var(--pb-button-outline-bg-hover,rgb(255_255_255/0.3))]',
};

export function CTAButton({ label, href, variant, size = 'lg' }: CTAButtonProps) {
  if (!label || label.trim() === '') return null;
  return (
    <a href={href || '#'} className={cn(BASE, SIZE_CLASSES[size], VARIANT_CLASSES[variant])}>
      {/* The label is already inside this <a>, so links stay markup-free —
			    a nested anchor is invalid HTML and browsers split it. */}
      {renderRichText(label, { allowLinks: false })}
      {/* Trailing arrow, off by default. Tenants flip it on globally via
			    `--pb-button-arrow-display` (e.g. inline-block) — no content change.
			    Labels that already carry their own arrow (a literal "→", or a "←"
			    back link) suppress it, so the global toggle never doubles or
			    contradicts an explicit direction. */}
      {!/[←→]/.test(label) && (
        <span aria-hidden="true" className="ml-2 [display:var(--pb-button-arrow-display,none)]">
          →
        </span>
      )}
    </a>
  );
}
