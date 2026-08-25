/**
 * The blocks an article body is made of.
 *
 * Deliberately a small, prose-shaped set rather than a copy of pagebuilder's
 * widget catalogue. That catalogue exists to build *pages* — heroes, feature
 * grids, logo clouds, site headers — and almost none of it belongs in a news
 * story. Cloning it to avoid depending on it would have been the worst of both
 * options: the same maintenance surface, twice, for blocks nobody puts in an
 * article.
 *
 * A host that wants the full palette on an article can still have it: install
 * pagebuilder, build the page there, and link to it. This is the set for
 * writing.
 *
 * Self-contained by design — Tailwind utilities only, no pagebuilder theme
 * tokens — because these render on the public article page, which has to work
 * on a host that never installed that module.
 */

import type { ComponentConfig } from '@puckeditor/core';

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

export interface ImageProps {
  url: string;
  alt: string;
  caption: string;
}

export const ImageBlock: ComponentConfig<ImageProps> = {
  label: 'Image',
  fields: {
    // A plain URL rather than a media picker: the library belongs to
    // pagebuilder, and this block has to work without it. Where that module is
    // installed, its library hands out exactly this — a URL to paste.
    url: { type: 'text', label: 'Image URL' },
    alt: { type: 'text', label: 'Alt text (describe the image)' },
    caption: { type: 'text', label: 'Caption (optional)' },
  },
  defaultProps: { url: '', alt: '', caption: '' },
  render: ({ url, alt, caption }) => {
    if (!url) return <></>;
    return (
      <figure className="my-8">
        <img src={url} alt={alt} loading="lazy" className="w-full rounded-lg" />
        {caption && (
          <figcaption className="mt-2 text-sm text-muted-foreground">{caption}</figcaption>
        )}
      </figure>
    );
  },
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
    // One item per line rather than Puck's array field: a writer pasting a
    // bulleted list from a document gets it in one action instead of clicking
    // "add item" nine times.
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
    const lines = (items || '')
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean);
    if (lines.length === 0) return <></>;
    const className = ordered
      ? 'mb-4 list-decimal space-y-1 pl-6'
      : 'mb-4 list-disc space-y-1 pl-6';
    return ordered ? (
      <ol className={className}>
        {lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ol>
    ) : (
      <ul className={className}>
        {lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    );
  },
};

export interface DividerProps {
  spacing: 'small' | 'large';
}

export const DividerBlock: ComponentConfig<DividerProps> = {
  label: 'Divider',
  fields: {
    spacing: {
      type: 'select',
      label: 'Spacing',
      options: [
        { label: 'Small', value: 'small' },
        { label: 'Large', value: 'large' },
      ],
    },
  },
  defaultProps: { spacing: 'small' },
  render: ({ spacing }) => <hr className={spacing === 'large' ? 'my-12' : 'my-6'} />,
};

export interface EmbedProps {
  url: string;
  title: string;
  ratio: '16/9' | '4/3';
}

export const EmbedBlock: ComponentConfig<EmbedProps> = {
  label: 'Embed (video, map…)',
  fields: {
    url: { type: 'text', label: 'Embed URL' },
    title: { type: 'text', label: 'Title (read by screen readers)' },
    ratio: {
      type: 'select',
      label: 'Aspect ratio',
      options: [
        { label: '16:9', value: '16/9' },
        { label: '4:3', value: '4/3' },
      ],
    },
  },
  defaultProps: { url: '', title: 'Embedded media', ratio: '16/9' },
  render: ({ url, title, ratio }) => {
    if (!url) return <></>;
    return (
      <div
        className="my-8 overflow-hidden rounded-lg"
        style={{ aspectRatio: ratio === '4/3' ? '4 / 3' : '16 / 9' }}
      >
        <iframe
          src={url}
          title={title}
          loading="lazy"
          allowFullScreen
          className="size-full border-0"
        />
      </div>
    );
  },
};
