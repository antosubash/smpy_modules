import type { ComponentConfig } from '@puckeditor/core';
import type { CSSProperties } from 'react';
import { keys } from '../../utils/i18n';
import { AccentText } from './_internal/accent-text';
import { RichTextBlock, renderRichText } from './_internal/rich-text';

export type EyebrowSectionWidgetProps = {
  eyebrow: string;
  heading: string;
  body: string;
};

export const EyebrowSectionWidget: ComponentConfig<EyebrowSectionWidgetProps> = {
  label: keys.pagebuilder.blocks.eyebrow_section.label,
  fields: {
    eyebrow: { type: 'text', label: keys.pagebuilder.blocks.eyebrow_section.eyebrow },
    heading: { type: 'text', label: keys.pagebuilder.blocks.common.heading },
    body: { type: 'textarea', label: keys.pagebuilder.blocks.common.body },
  },
  defaultProps: {
    eyebrow: 'Our story',
    heading: 'How we got here',
    body: 'Body text describing the section in more detail.',
  },
  render: ({ eyebrow, heading, body }) => (
    <section className="container mx-auto px-4 py-12 max-w-3xl">
      {eyebrow && (
        <p className="text-sm font-semibold uppercase tracking-wider text-primary-700">
          {renderRichText(eyebrow)}
        </p>
      )}
      {/* AccentText, not bare renderRichText: this is a display heading on
				    `--pb-display-weight`, where a plain <strong>'s relative `bolder`
				    can compute to no visible change. */}
      {heading && (
        <h2
          className="mt-2 text-2xl sm:text-3xl lg:text-4xl"
          style={{
            fontWeight: 'var(--pb-display-weight)' as CSSProperties['fontWeight'],
            letterSpacing: 'var(--pb-display-tracking)',
            fontFamily: 'var(--pb-display-font)',
            color: 'var(--pb-heading-color)',
          }}
        >
          <AccentText text={heading} />
        </h2>
      )}
      {body && (
        <RichTextBlock
          text={body}
          className="mt-4 text-lg leading-relaxed"
          style={{ color: 'var(--pb-body-color)' }}
        />
      )}
    </section>
  ),
};
