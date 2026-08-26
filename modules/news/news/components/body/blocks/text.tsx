/**
 * The blocks an article's running prose is made of.
 *
 * See `./index.ts` for what governs this palette as a whole.
 */

import type { ComponentConfig } from '@puckeditor/core';

import { itemKey, lines } from './lines';

export interface HeadingProps {
  text: string;
  level: '2' | '3';
}

/** Levels start at 2: the article's own title is the page's `<h1>`, so a
 *  body heading that claimed it would give the document two. */
export const HeadingBlock: ComponentConfig<HeadingProps> = {
  label: 'Heading',
  fields: {
    text: { type: 'text', label: 'Text' },
    level: {
      type: 'select',
      label: 'Level',
      options: [
        { label: 'Section (H2)', value: '2' },
        { label: 'Sub-section (H3)', value: '3' },
      ],
    },
  },
  defaultProps: { text: 'Section heading', level: '2' },
  render: ({ text, level }) =>
    level === '3' ? (
      <h3 className="mt-8 mb-3 text-xl font-semibold tracking-tight">{text}</h3>
    ) : (
      <h2 className="mt-10 mb-4 text-2xl font-semibold tracking-tight">{text}</h2>
    ),
};

export interface ParagraphProps {
  text: string;
  lead: boolean;
}

export const ParagraphBlock: ComponentConfig<ParagraphProps> = {
  label: 'Paragraph',
  fields: {
    text: { type: 'textarea', label: 'Text' },
    lead: {
      type: 'radio',
      label: 'Style',
      options: [
        { label: 'Body', value: false },
        { label: 'Lead (larger)', value: true },
      ],
    },
  },
  defaultProps: { text: '', lead: false },
  render: ({ text, lead }) => (
    // `whitespace-pre-line` so a writer's line breaks survive. The field is a
    // textarea; silently collapsing what they typed there reads as a bug.
    <p
      className={
        lead
          ? 'mb-6 whitespace-pre-line text-lg leading-relaxed text-muted-foreground'
          : 'mb-4 whitespace-pre-line leading-relaxed'
      }
    >
      {text}
    </p>
  ),
};

export interface QuoteProps {
  text: string;
  attribution: string;
}

export const QuoteBlock: ComponentConfig<QuoteProps> = {
  label: 'Pull quote',
  fields: {
    text: { type: 'textarea', label: 'Quote' },
    attribution: { type: 'text', label: 'Attribution (optional)' },
  },
  defaultProps: { text: '', attribution: '' },
  render: ({ text, attribution }) => (
    <blockquote className="my-8 border-l-4 border-primary/40 pl-5 italic">
      <p className="whitespace-pre-line text-lg leading-relaxed">{text}</p>
      {attribution && (
        <footer className="mt-2 text-sm not-italic text-muted-foreground">— {attribution}</footer>
      )}
    </blockquote>
  ),
};

export interface ListProps {
  items: string;
  ordered: boolean;
}

export const ListBlock: ComponentConfig<ListProps> = {
  label: 'List',
  fields: {
    // One item per line rather than Puck's array field — see `./lines`.
    items: { type: 'textarea', label: 'One item per line' },
    ordered: {
      type: 'radio',
      label: 'Style',
      options: [
        { label: 'Bulleted', value: false },
        { label: 'Numbered', value: true },
      ],
    },
  },
  defaultProps: { items: '', ordered: false },
  render: ({ items, ordered }) => {
    const entries = lines(items);
    if (entries.length === 0) return <></>;
    const className = ordered
      ? 'mb-4 list-decimal space-y-1 pl-6'
      : 'mb-4 list-disc space-y-1 pl-6';
    return ordered ? (
      <ol className={className}>
        {entries.map((line, index) => (
          <li key={itemKey(line, index)}>{line}</li>
        ))}
      </ol>
    ) : (
      <ul className={className}>
        {entries.map((line, index) => (
          <li key={itemKey(line, index)}>{line}</li>
        ))}
      </ul>
    );
  },
};
