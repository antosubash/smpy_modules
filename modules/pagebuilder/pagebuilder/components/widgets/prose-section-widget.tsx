import type { ComponentConfig } from '@puckeditor/core';
import { cn } from '../../utils/widgetUtils';
import { AccentText } from './_internal/accent-text';
import { EyebrowSplitSection } from './_internal/eyebrow-split-section';
import { renderRichText } from './_internal/rich-text';

export type ProseSectionWidgetProps = {
  eyebrow: string;
  heading: string;
  subheading: string;
  body: string;
  surface: 'default' | 'muted';
  /**
   * "prose" is the default running-text block. "questions" is the Figma's
   * open-research-questions treatment: each paragraph is a large statement
   * (36px) set well apart from the next (32px), with `*word*` segments picked
   * out in the brand accent colour instead of inheriting.
   */
  variant?: 'prose' | 'questions';
};

function paragraphs(body: string): string[] {
  return body
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean);
}

export const ProseSectionWidget: ComponentConfig<ProseSectionWidgetProps> = {
  label: 'Prose section (eyebrow + heading + rich body)',
  fields: {
    eyebrow: { type: 'text', label: 'Eyebrow' },
    heading: { type: 'text', label: 'Heading' },
    subheading: { type: 'text', label: 'Lead sub-heading (optional)' },
    body: {
      type: 'textarea',
      label: 'Body (blank line = new paragraph)',
    },
    surface: {
      type: 'select',
      label: 'Surface',
      options: [
        { label: 'Default', value: 'default' },
        { label: 'Muted (soft card)', value: 'muted' },
      ],
    },
    variant: {
      type: 'select',
      label: 'Body style',
      options: [
        { label: 'Prose', value: 'prose' },
        { label: 'Questions (large, accented)', value: 'questions' },
      ],
    },
  },
  defaultProps: {
    eyebrow: 'Explanation',
    heading: 'Explanation',
    subheading: '',
    body: 'Describe the topic here.',
    surface: 'muted',
    variant: 'prose',
  },
  render: ({ eyebrow, heading, subheading, body, surface = 'default', variant = 'prose' }) => (
    <EyebrowSplitSection eyebrow={eyebrow} heading={heading} muted={surface === 'muted'}>
      <div className={cn('flex flex-col', variant === 'questions' ? 'gap-8' : 'gap-4')}>
        {subheading && (
          <p className="font-semibold" style={{ color: 'var(--pb-heading-color)' }}>
            {renderRichText(subheading)}
          </p>
        )}
        {paragraphs(body).map((para, i) => (
          <p
            // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
            key={i}
            // Size first, leading second: tailwind-merge treats a font-size
            // utility as also setting line-height, so a `leading-*` placed
            // BEFORE `text-lg` is dropped from the merged result.
            className={cn(
              variant === 'questions'
                ? 'text-[length:var(--pb-prose-question-size,2.25rem)] leading-tight'
                : 'text-lg leading-[var(--pb-body-leading,1.625)]',
            )}
            style={{
              color: variant === 'questions' ? 'var(--pb-heading-color)' : 'var(--pb-body-color)',
            }}
          >
            {/* `*word*` picks out the highlighted phrase; only the questions
						    variant recolours it, so ordinary prose is unchanged. */}
            <AccentText
              text={para}
              color={variant === 'questions' ? 'var(--pb-accent)' : undefined}
            />
          </p>
        ))}
      </div>
    </EyebrowSplitSection>
  ),
};
