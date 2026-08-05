import type { ComponentConfig } from '@puckeditor/core';
import { useMemo } from 'react';
import { parseMarkdownBlocks as renderMarkdown } from '../../utils/markdown';
import { renderRichText } from './_internal/rich-text';

export type MarkdownWidgetProps = {
  content: string;
  /**
   * Text column width. "auto" is the legacy centred `max-w-4xl`; "660" is the
   * Figma's measure for the legal and event pages.
   */
  width?: 'auto' | '660';
  /**
   * Left placement on the 12-column page grid. "none" keeps the centred
   * column; "4" starts the text at the 4th column, as the Figma does.
   */
  indent?: 'none' | '4';
};

// Emphasis tokenization is shared with the markdown→HTML converter; links are
// layered on top of it by renderRichText, which is also what the FAQ answers
// use — before that, `[label](href)` rendered here as literal text.
const renderInline = renderRichText;

export const MarkdownWidget: ComponentConfig<MarkdownWidgetProps> = {
  label: 'Markdown',
  fields: {
    width: {
      type: 'select',
      label: 'Text width',
      options: [
        { label: 'Auto (centred)', value: 'auto' },
        { label: '660px', value: '660' },
      ],
    },
    indent: {
      type: 'select',
      label: 'Grid indent',
      options: [
        { label: 'None', value: 'none' },
        { label: '4th column', value: '4' },
      ],
    },
    content: {
      type: 'textarea',
      label: 'Markdown content',
    },
  },
  defaultProps: {
    width: 'auto',
    indent: 'none',
    content: '# Heading\n\nBody paragraph text.\n\n## Subheading\n\n- First item\n- Second item',
  },
  render: (props) => <MarkdownRender {...props} />,
};

function MarkdownRender({ content, width = 'auto', indent = 'none' }: MarkdownWidgetProps) {
  const blocks = useMemo(() => renderMarkdown(content || ''), [content]);
  const indented = indent === '4';
  return (
    <div
      className={`container mx-auto px-4 py-8${indented ? ' lg:grid lg:grid-cols-12 lg:gap-6' : ''}`}
    >
      <div
        className={[
          // `--pb-prose-link-color` lets a tenant colour links (BioGarden's
          // Figma uses the brand purple); unset, links keep the prose default.
          'prose prose-lg dark:prose-invert break-words [&_a]:text-[color:var(--pb-prose-link-color,inherit)]',
          // The last block's own `mb-4` sits BELOW the text and stacks on top
          // of this section's bottom padding, so the visible gap to whatever
          // follows is 16px wider than the padding says. A tenant measuring
          // exact gaps off a Figma (BioGarden: 48px text→image, 40px
          // text→CTA) sets `--pb-prose-trailing-mb: 0` to make the section
          // padding the whole gap; the 1rem fallback matches every block
          // type's own mb-4 (h3's mb-3 is the one exception — content ending
          // on a bare h3 gains 4px).
          '[&>*:last-child]:mb-[var(--pb-prose-trailing-mb,1rem)]',
          width === '660' ? 'max-w-[660px]' : 'max-w-4xl',
          // Indented text starts at the 4th grid column instead of centring.
          indented ? 'lg:col-start-4 lg:col-span-9' : 'mx-auto',
        ].join(' ')}
      >
        {blocks.map((block, idx) => {
          if (block.type === 'h1')
            return (
              <h1
                // biome-ignore lint/suspicious/noArrayIndexKey: blocks are positional slices of one string, re-derived each render
                key={idx}
                // `**key words**` must read as semibold against the light
                // display weight. `<strong>`'s default `bolder` is RELATIVE,
                // so on a 300-weight heading it resolves to 400 and the
                // emphasis is invisible — state the weight explicitly.
                // `leading-[calc(2.5/2.25)]` restores what `text-4xl` bundles:
                // Tailwind's font-size utilities also set a line-height, and
                // `text-[length:…]` sets ONLY the size. The `prose` classes
                // can't cover for it — @tailwindcss/typography is not
                // installed, so they compile to nothing. Unitless keeps the
                // old 2.25rem/2.5rem ratio exactly while scaling with a
                // tenant's larger heading. Size first, leading second (the
                // reverse order is silently dropped by tailwind-merge).
                className="text-[length:var(--pb-prose-h1-size,2.25rem)] leading-[calc(2.5/2.25)] font-light mb-4 [&_strong]:font-semibold"
              >
                {renderInline(block.text)}
              </h1>
            );
          if (block.type === 'h2')
            return (
              // Token-sized like the H1 above: the fallback reproduces the
              // previous `text-3xl` (size AND its bundled 1.2 line-height),
              // while a pack can scale prose H2s per breakpoint — without
              // this, a mobile pack that shrinks the H1 leaves section H2s
              // LARGER than the page title (BioGarden QA, SUB-36).
              <h2
                // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
                key={idx}
                className="text-[length:var(--pb-prose-h2-size,1.875rem)] leading-[1.2] font-light mt-8 mb-4"
              >
                {renderInline(block.text)}
              </h2>
            );
          if (block.type === 'h3')
            return (
              // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
              <h3 key={idx} className="text-2xl font-semibold mt-6 mb-3">
                {renderInline(block.text)}
              </h3>
            );
          if (block.type === 'ul')
            return (
              // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
              <ul key={idx} className="list-disc list-inside space-y-1 mb-4">
                {block.items.map((item, i) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
                  <li key={i}>{renderInline(item)}</li>
                ))}
              </ul>
            );
          return (
            // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
            <p key={idx} className="leading-relaxed mb-4">
              {renderInline(block.text)}
            </p>
          );
        })}
      </div>
    </div>
  );
}
