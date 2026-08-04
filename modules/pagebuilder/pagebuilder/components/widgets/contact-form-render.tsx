/** Contact form types and render — split from contact-form-widget.tsx,
 *  which keeps the field definitions, so both stay under the 300-line cap. */

import { type FormEvent, useId, useState } from 'react';
import { parseList } from '../../utils/widgetUtils';
import { AccentText } from './_internal/accent-text';
import { RichTextBlock, renderRichText } from './_internal/rich-text';

export type ContactFormWidgetProps = {
  variant: 'boxed' | 'underline';
  /**
   * Optional CSS color for the form panel. When set, the panel renders on that
   * color with inverse (white) labels, underline fields and an outline pill
   * submit; blank keeps the default grey panel.
   */
  surfaceColor: string;
  title: string;
  subtitle: string;
  nameLabel: string;
  namePlaceholder: string;
  orgLabel: string;
  orgPlaceholder: string;
  enquiryLabel: string;
  enquiryOptions: string;
  emailLabel: string;
  emailPlaceholder: string;
  messageLabel: string;
  messagePlaceholder: string;
  termsLabel: string;
  submitLabel: string;
  successTitle: string;
  successBody: string;
};

const HEADING_STYLE = { color: 'var(--pb-heading-color)' };
const BODY_STYLE = { color: 'var(--pb-body-color)' };
// Text on a colored (surfaceColor) panel — the shared inverse-on-color token.
const INVERSE_STYLE = { color: 'var(--pb-surface-contrast, #ffffff)' };
const INPUT_CLASS =
  'w-full border rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary-500';
const INPUT_STYLE = {
  borderColor: 'var(--border)',
  color: 'var(--pb-body-color)',
};
// Boxed field, inverse (on a colored panel): translucent white fill + rule.
const INPUT_INVERSE_CLASS =
  'w-full rounded-md border border-white/60 bg-white/10 px-3 py-2 placeholder:text-white/70 focus:outline-none focus:ring-2 focus:ring-white/50';
// Underline variant (GCA): borderless field with only a bottom rule, on a soft
// grey panel, label-as-placeholder.
const UNDERLINE_INPUT_CLASS =
  'w-full bg-transparent border-0 border-b border-[#686873]/50 px-0 py-4 text-xl text-[var(--pb-heading-color)] placeholder:text-[#686873] focus:outline-none focus:border-[var(--pb-heading-color)]';
// Underline field, inverse (on a colored panel): white rule + placeholder.
const UNDERLINE_INPUT_INVERSE_CLASS =
  'w-full bg-transparent border-0 border-b border-white/60 px-0 py-4 text-xl placeholder:text-white/70 focus:outline-none focus:border-white';

export function ContactFormRender({
  variant,
  surfaceColor,
  title,
  subtitle,
  nameLabel,
  namePlaceholder,
  orgLabel,
  orgPlaceholder,
  enquiryLabel,
  enquiryOptions,
  emailLabel,
  emailPlaceholder,
  messageLabel,
  messagePlaceholder,
  termsLabel,
  submitLabel,
  successTitle,
  successBody,
}: ContactFormWidgetProps) {
  const nameId = useId();
  const orgId = useId();
  const enquiryId = useId();
  const emailId = useId();
  const messageId = useId();
  const termsId = useId();
  const [submitted, setSubmitted] = useState(false);
  const options = parseList(enquiryOptions);
  const underline = variant === 'underline';
  // A colored panel flips fields/labels to inverse (white) styling.
  const inverse = Boolean(surfaceColor);
  const inputClass = inverse
    ? underline
      ? UNDERLINE_INPUT_INVERSE_CLASS
      : INPUT_INVERSE_CLASS
    : underline
      ? UNDERLINE_INPUT_CLASS
      : INPUT_CLASS;
  const inputStyle = inverse ? INVERSE_STYLE : underline ? undefined : INPUT_STYLE;
  const labelClass = underline ? 'sr-only' : 'block text-sm font-medium mb-1';
  const labelStyle = inverse ? INVERSE_STYLE : HEADING_STYLE;
  const panelBodyStyle = inverse ? INVERSE_STYLE : BODY_STYLE;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitted(true);
  }

  return (
    <section
      className={
        underline
          ? 'container mx-auto px-4 py-[var(--pb-section-py,3rem)] sm:px-6 lg:px-8'
          : 'container mx-auto py-[var(--pb-section-py,3rem)] px-4 max-w-2xl'
      }
    >
      {(title || subtitle) && (
        <div className="text-center mb-8">
          {/* AccentText, not bare renderRichText: `font-light` (300) here makes
					    a plain <strong>'s relative `bolder` compute to 400 — no visible
					    change. */}
          {title && (
            <h2 className="text-3xl sm:text-4xl lg:text-5xl font-light" style={HEADING_STYLE}>
              <AccentText text={title} />
            </h2>
          )}
          {subtitle && (
            <RichTextBlock text={subtitle} className="mt-3 text-lg" style={BODY_STYLE} />
          )}
        </div>
      )}
      <div
        className={
          inverse
            ? 'mx-auto max-w-3xl rounded-[12px] px-6 py-10 sm:px-12 sm:py-12'
            : underline
              ? 'mx-auto max-w-3xl rounded-[12px] bg-[var(--pb-surface-muted,#f3f3f4)] px-6 py-10 sm:px-12 sm:py-12'
              : ''
        }
        style={inverse ? { backgroundColor: surfaceColor } : undefined}
      >
        {submitted ? (
          <div
            className="rounded-md border px-6 py-8 text-center"
            style={inverse ? { borderColor: 'rgba(255,255,255,0.6)' } : INPUT_STYLE}
          >
            {successTitle && (
              <h3 className="text-xl font-medium" style={labelStyle}>
                {renderRichText(successTitle)}
              </h3>
            )}
            {successBody && (
              <RichTextBlock text={successBody} className="mt-2" style={panelBodyStyle} />
            )}
          </div>
        ) : (
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div>
              <label htmlFor={nameId} className={labelClass} style={labelStyle}>
                {renderRichText(nameLabel)}
              </label>
              <input
                id={nameId}
                type="text"
                required
                placeholder={namePlaceholder}
                className={inputClass}
                style={inputStyle}
              />
            </div>
            <div>
              <label htmlFor={emailId} className={labelClass} style={labelStyle}>
                {renderRichText(emailLabel)}
              </label>
              <input
                id={emailId}
                type="email"
                required
                placeholder={emailPlaceholder}
                className={inputClass}
                style={inputStyle}
              />
            </div>
            {orgLabel && (
              <div>
                <label htmlFor={orgId} className={labelClass} style={labelStyle}>
                  {renderRichText(orgLabel)}
                </label>
                <input
                  id={orgId}
                  type="text"
                  placeholder={orgPlaceholder}
                  className={inputClass}
                  style={inputStyle}
                />
              </div>
            )}
            <div>
              <label htmlFor={enquiryId} className={labelClass} style={labelStyle}>
                {renderRichText(enquiryLabel)}
              </label>
              <select
                id={enquiryId}
                required
                className={inputClass}
                style={inputStyle}
                defaultValue=""
              >
                <option value="" disabled>
                  {underline ? enquiryLabel || 'Select…' : 'Select…'}
                </option>
                {options.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor={messageId} className={labelClass} style={labelStyle}>
                {renderRichText(messageLabel)}
              </label>
              <textarea
                id={messageId}
                required
                placeholder={messagePlaceholder}
                rows={5}
                className={inputClass}
                style={inputStyle}
              />
            </div>
            <div className="flex items-start gap-2">
              <input
                id={termsId}
                type="checkbox"
                required
                className="mt-1"
                style={{
                  accentColor: inverse ? 'var(--pb-surface-contrast, #ffffff)' : 'var(--primary)',
                }}
              />
              <label htmlFor={termsId} className="text-sm" style={panelBodyStyle}>
                {/* `*word*` segments render in the accent colour (e.g. the
								    orange "Terms of Use" link in the Figma); on a colored
								    panel they invert to the surface-contrast color, underlined.
								    The rest is ordinary inline markdown, so the terms can also
								    carry a real `[link](/page/terms)`. */}
                {renderRichText(termsLabel, {
                  renderEm: (content, key) => (
                    <span
                      key={key}
                      className={inverse ? 'font-semibold underline' : 'font-semibold'}
                      style={{
                        color: inverse
                          ? 'var(--pb-surface-contrast, #ffffff)'
                          : 'var(--pb-accent, #fa6e25)',
                      }}
                    >
                      {content}
                    </span>
                  ),
                })}
              </label>
            </div>
            <button
              type="submit"
              className={
                inverse
                  ? 'inline-flex items-center justify-center rounded-full border px-6 py-3 font-semibold transition-colors hover:bg-white/10'
                  : underline
                    ? 'inline-flex items-center justify-center rounded-full bg-[var(--primary,#1a353e)] px-6 py-3 font-semibold text-[var(--primary-foreground,#fff)] transition-opacity hover:opacity-90'
                    : 'inline-flex items-center justify-center px-5 py-2.5 rounded-md bg-primary-700 hover:bg-primary-800 text-white font-medium'
              }
              style={
                inverse
                  ? {
                      borderColor: 'var(--pb-surface-contrast, #ffffff)',
                      color: 'var(--pb-surface-contrast, #ffffff)',
                      backgroundColor: 'transparent',
                    }
                  : undefined
              }
            >
              {renderRichText(submitLabel, { allowLinks: false })}
              {/* Trailing arrow, off by default (`--pb-button-arrow-display`). */}
              <span
                aria-hidden="true"
                className="ml-2 [display:var(--pb-button-arrow-display,none)]"
              >
                →
              </span>
            </button>
          </form>
        )}
      </div>
    </section>
  );
}
