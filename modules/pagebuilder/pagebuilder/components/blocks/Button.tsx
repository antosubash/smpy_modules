import type { ComponentConfig } from '@puckeditor/core';
import type { CSSProperties } from 'react';

import { cn } from '../../utils/widgetUtils';
import { renderRichText } from '../widgets/_internal/rich-text';

interface ButtonProps {
  label: string;
  href: string;
  variant: 'primary' | 'secondary' | 'outline' | 'ghost';
  size: 'sm' | 'md' | 'lg';
  target: '_self' | '_blank';
  /**
   * Optional CSS colour override. "primary" uses it as the background (with
   * `--pb-surface-contrast` text); the other variants use it as the text and
   * border colour. Blank keeps the variant's own palette.
   */
  color: string;
  /**
   * Left placement on the 12-column page grid. "none" keeps the button at the
   * container's left edge; "4" starts it at the 4th column so it lines up with
   * an indented text column (the Markdown widget's `indent`).
   */
  indent: 'none' | '4';
}

// `primary`/`ghost` read the branding ramp rather than a fixed blue, so the
// button follows Settings → Branding like the rest of the widget set. The
// previous `bg-blue-600` ignored it.
const variantClass: Record<ButtonProps['variant'], string> = {
  primary: 'bg-primary-700 hover:bg-primary-800 text-white',
  secondary: 'bg-gray-700 hover:bg-gray-800 text-white',
  outline:
    'border border-gray-300 text-gray-900 hover:bg-gray-50 dark:text-white dark:border-gray-700 dark:hover:bg-gray-800',
  ghost:
    'text-[color:var(--pb-button-ghost-fg,var(--color-primary-700))] hover:bg-[var(--pb-button-ghost-bg-hover,var(--color-primary-50))]',
};

const sizeClass: Record<ButtonProps['size'], string> = {
  sm: 'py-1.5 px-3 text-sm',
  md: 'py-2 px-5 text-base',
  lg: 'py-3 px-7 text-lg',
};

export const ButtonBlock: ComponentConfig<ButtonProps> = {
  label: 'Button',
  fields: {
    label: { type: 'text', label: 'Label' },
    href: { type: 'text', label: 'Link' },
    variant: {
      type: 'select',
      label: 'Variant',
      options: [
        { label: 'Primary', value: 'primary' },
        { label: 'Secondary', value: 'secondary' },
        { label: 'Outline', value: 'outline' },
        { label: 'Ghost', value: 'ghost' },
      ],
    },
    size: {
      type: 'select',
      label: 'Size',
      options: [
        { label: 'Small', value: 'sm' },
        { label: 'Medium', value: 'md' },
        { label: 'Large', value: 'lg' },
      ],
    },
    target: {
      type: 'radio',
      label: 'Link target',
      options: [
        { label: 'Same tab', value: '_self' },
        { label: 'New tab', value: '_blank' },
      ],
    },
    color: { type: 'text', label: 'Colour (CSS, optional)' },
    indent: {
      type: 'select',
      label: 'Grid indent',
      options: [
        { label: 'None', value: 'none' },
        { label: '4th column', value: '4' },
      ],
    },
  },
  defaultProps: {
    label: 'Click me',
    href: '#',
    variant: 'primary',
    size: 'md',
    target: '_self',
    color: '',
    indent: 'none',
  },
  // `size`, `color` and `indent` are defaulted again in the signature, not
  // only in `defaultProps`. Those apply to a block the author drops *now* —
  // every Button already stored on a page predates these fields and arrives
  // with them undefined, which would index the class maps to `undefined` and
  // put that literal into the class list.
  render: ({ label, href, variant, size = 'md', target, color = '', indent = 'none' }) => {
    // Pill radius is theme-driven; the fallback is the previous `rounded`.
    const style: CSSProperties = { borderRadius: 'var(--pb-button-radius, 0.375rem)' };
    if (color) {
      if (variant === 'primary') {
        style.backgroundColor = color;
        style.color = 'var(--pb-surface-contrast, #ffffff)';
      } else {
        style.color = color;
        style.borderColor = color;
      }
    }
    return (
      <div className={cn(indent === '4' && 'lg:grid lg:grid-cols-12 lg:gap-6')}>
        <a
          href={href}
          target={target}
          rel={target === '_blank' ? 'noopener noreferrer' : undefined}
          className={cn(
            'inline-flex items-center justify-center font-medium transition-colors',
            indent === '4' && 'lg:col-start-4 lg:col-span-9 lg:justify-self-start',
            variantClass[variant],
            sizeClass[size],
          )}
          style={style}
        >
          {/* Links off: this is already inside an `<a>`, and nesting anchors
              is invalid HTML. */}
          {renderRichText(label || '', { allowLinks: false })}
          {/* Trailing arrow, off by default (`--pb-button-arrow-display`) and
              suppressed when the label carries its own — a "← Back" link
              should not come out as "← Back →". */}
          {!/[←→]/.test(label ?? '') && (
            <span aria-hidden="true" className="ml-2 [display:var(--pb-button-arrow-display,none)]">
              →
            </span>
          )}
        </a>
      </div>
    );
  },
};
