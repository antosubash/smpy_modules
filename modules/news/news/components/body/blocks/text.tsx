/**
 * The blocks an article's running prose is made of.
 *
 * See `./index.ts` for what governs this palette as a whole.
 */

import type { ComponentConfig } from '@puckeditor/core';

import { keys } from '../../../utils/i18n';

import { cells, itemKey, lines } from './lines';
import { headingAnchor, outlineFromMetadata } from './outline';

export interface HeadingProps {
  text: string;
  level: '2' | '3';
}

/** Levels start at 2: the article's own title is the page's `<h1>`, so a
 *  body heading that claimed it would give the document two.
 *
 *  Each one carries an `id` so `Contents` has something to link to, and so a
 *  reader can share a link to the section rather than to the article. The id
 *  comes from the document's outline rather than from this block's own text —
 *  see `./outline.ts`: only the document knows whether this is the first
 *  "Background" or the second. */
export const HeadingBlock: ComponentConfig<HeadingProps> = {
  label: keys.news.blocks.heading.label,
  fields: {
    text: { type: 'text', label: keys.news.blocks.common.text },
    level: {
      type: 'select',
      label: keys.news.blocks.heading.level,
      options: [
        { label: keys.news.blocks.heading.level_h2, value: '2' },
        { label: keys.news.blocks.heading.level_h3, value: '3' },
      ],
    },
  },
  defaultProps: { text: 'Section heading', level: '2' },
  render: ({ id, level, puck, text }) => {
    const anchor = headingAnchor(id, text, outlineFromMetadata(puck?.metadata));
    return level === '3' ? (
      <h3 id={anchor} className="mt-8 mb-3 text-xl font-semibold tracking-tight">
        {text}
      </h3>
    ) : (
      <h2 id={anchor} className="mt-10 mb-4 text-2xl font-semibold tracking-tight">
        {text}
      </h2>
    );
  },
};

export interface ParagraphProps {
  text: string;
  lead: boolean;
}

export const ParagraphBlock: ComponentConfig<ParagraphProps> = {
  label: keys.news.blocks.paragraph.label,
  fields: {
    text: { type: 'textarea', label: keys.news.blocks.common.text },
    lead: {
      type: 'radio',
      label: keys.news.blocks.common.style,
      options: [
        { label: keys.news.blocks.paragraph.style_body, value: false },
        { label: keys.news.blocks.paragraph.style_lead, value: true },
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
  label: keys.news.blocks.quote.label,
  fields: {
    text: { type: 'textarea', label: keys.news.blocks.quote.text },
    attribution: { type: 'text', label: keys.news.blocks.quote.attribution },
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

export interface QandAProps {
  title: string;
  items: string;
}

/**
 * An interview exchange.
 *
 * A description list, because that is what it is: each question introduces the
 * answer that follows it, and a screen reader announcing the pairing gives a
 * listener the structure a sighted reader gets from the indent. Written as
 * alternating paragraphs it is neither — just prose where every other sentence
 * happens to end in a question mark.
 */
export const QandABlock: ComponentConfig<QandAProps> = {
  label: keys.news.blocks.qanda.label,
  fields: {
    title: { type: 'text', label: keys.news.blocks.qanda.title },
    items: { type: 'textarea', label: keys.news.blocks.qanda.items },
  },
  defaultProps: { title: '', items: '' },
  render: ({ title, items }) => {
    const exchanges = lines(items).map((line) => cells(line, 2));
    if (exchanges.length === 0) return <></>;
    return (
      <section className="my-8">
        {title && (
          <p className="mb-4 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {title}
          </p>
        )}
        <dl className="space-y-5">
          {exchanges.map(([question, answer], index) => (
            <div key={itemKey(question, index)}>
              <dt className="font-semibold leading-relaxed">{question}</dt>
              <dd className="mt-1 ml-0 whitespace-pre-line leading-relaxed text-muted-foreground">
                {answer}
              </dd>
            </div>
          ))}
        </dl>
      </section>
    );
  },
};

export interface ListProps {
  items: string;
  ordered: boolean;
}

export const ListBlock: ComponentConfig<ListProps> = {
  label: keys.news.blocks.list.label,
  fields: {
    // One item per line rather than Puck's array field — see `./lines`.
    items: { type: 'textarea', label: keys.news.blocks.list.items },
    ordered: {
      type: 'radio',
      label: keys.news.blocks.common.style,
      options: [
        { label: keys.news.blocks.list.style_bulleted, value: false },
        { label: keys.news.blocks.list.style_numbered, value: true },
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
