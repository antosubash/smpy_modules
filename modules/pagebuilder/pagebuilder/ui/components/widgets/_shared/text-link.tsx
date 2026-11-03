import type { CSSProperties } from 'react';
import { cn } from '../../../utils/widgetUtils';
import { LinkArrow } from '../_internal/link-arrow';
import { renderRichText } from '../_internal/rich-text';

/**
 * Inline text link with a trailing arrow ("View all", "Learn more", …), themed
 * via the tenant link tokens: `--pb-link-color` / `--pb-link-hover-color` /
 * `--pb-link-hover-decoration` / `--pb-link-size` / `--pb-link-weight`
 * (GCA: ink 18px SemiBold, teal hover, no underline). The fallbacks reproduce
 * the prior widget styling (accent-coloured 14px medium, underline on hover)
 * so tenants that don't set the tokens render unchanged.
 */

// Hoisted: a fresh style object per render would defeat React's prop-equality
// fast-path (see the same pattern on MESH_STYLE in _shared/background-media).
const LINK_TEXT_STYLE: CSSProperties = {
  fontSize: 'var(--pb-link-size, 0.875rem)',
  fontWeight: 'var(--pb-link-weight, 500)' as CSSProperties['fontWeight'],
};

export function TextLink({
  label,
  href,
  className,
}: {
  label: string;
  href: string;
  className?: string;
}) {
  if (!label || !href) return null;
  return (
    <a
      href={href}
      className={cn(
        'inline-flex shrink-0 items-center gap-2 whitespace-nowrap text-[color:var(--pb-link-color,var(--pb-accent))] underline-offset-4 hover:text-[color:var(--pb-link-hover-color,var(--pb-link-color,var(--pb-accent)))] hover:[text-decoration-line:var(--pb-link-hover-decoration,underline)]',
        className,
      )}
      style={LINK_TEXT_STYLE}
    >
      {/* Emphasis only: the label already sits inside this <a>, and a nested
			    anchor is invalid HTML that browsers split into two links. */}
      {renderRichText(label, { allowLinks: false })}
      <LinkArrow className="size-5" />
    </a>
  );
}
