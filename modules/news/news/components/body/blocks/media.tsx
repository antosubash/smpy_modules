/**
 * Pictures and embeds.
 *
 * Every image here is addressed by URL rather than picked from a library: the
 * library belongs to pagebuilder, and these have to render on a host that never
 * installed it. Where that module *is* installed, its picker hands out exactly
 * this — a URL to paste.
 */

import type { ComponentConfig } from '@puckeditor/core';

import { cells, itemKey, lines } from './lines';

export interface ImageProps {
  url: string;
  alt: string;
  caption: string;
  credit: string;
}

export const ImageBlock: ComponentConfig<ImageProps> = {
  label: 'Image',
  fields: {
    url: { type: 'text', label: 'Image URL' },
    alt: { type: 'text', label: 'Alt text (describe the image)' },
    caption: { type: 'text', label: 'Caption (optional)' },
    // Separate from the caption because it is a different obligation: a caption
    // explains the picture and a credit says whose it is, and a publication
    // that runs the second inside the first eventually runs a picture with
    // neither.
    credit: { type: 'text', label: 'Credit (optional)' },
  },
  defaultProps: { url: '', alt: '', caption: '', credit: '' },
  render: ({ url, alt, caption, credit }) => {
    if (!url) return <></>;
    return (
      <figure className="my-8">
        <img src={url} alt={alt} loading="lazy" className="w-full rounded-lg" />
        {(caption || credit) && (
          <figcaption className="mt-2 text-sm text-muted-foreground">
            {caption}
            {caption && credit ? ' ' : null}
            {credit && <span className="text-xs uppercase tracking-wide">{credit}</span>}
          </figcaption>
        )}
      </figure>
    );
  },
};

export interface GalleryProps {
  images: string;
  columns: '2' | '3';
}

/**
 * Several pictures as one figure.
 *
 * A grid rather than a carousel. A carousel hides all but one image behind an
 * interaction, which costs a reader who is scrolling the story the pictures
 * they were shown — and costs one reading it in a feed reader all of them.
 */
export const GalleryBlock: ComponentConfig<GalleryProps> = {
  label: 'Gallery',
  fields: {
    images: { type: 'textarea', label: 'One per line — "https://… | alt text | caption"' },
    columns: {
      type: 'select',
      label: 'Across',
      options: [
        { label: 'Two', value: '2' },
        { label: 'Three', value: '3' },
      ],
    },
  },
  defaultProps: { images: '', columns: '2' },
  render: ({ images, columns }) => {
    const entries = lines(images)
      .map((line) => cells(line, 3))
      .filter(([url]) => url);
    if (entries.length === 0) return <></>;
    // Full class strings — Tailwind reads this file as text, so a column count
    // spliced into a class name is one it never emits.
    const grid =
      columns === '3'
        ? 'grid grid-cols-2 gap-3 sm:grid-cols-3'
        : 'grid grid-cols-1 gap-3 sm:grid-cols-2';
    return (
      <figure className="my-8">
        <div className={grid}>
          {entries.map(([url, alt, caption], index) => (
            <figure key={itemKey(url, index)} className="m-0">
              <img src={url} alt={alt} loading="lazy" className="w-full rounded-lg" />
              {caption && (
                <figcaption className="mt-1.5 text-xs text-muted-foreground">{caption}</figcaption>
              )}
            </figure>
          ))}
        </div>
      </figure>
    );
  },
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
