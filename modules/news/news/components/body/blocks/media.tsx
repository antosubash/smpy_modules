/**
 * Pictures and embeds.
 *
 * Every image here is addressed by URL rather than picked from a library: the
 * library belongs to pagebuilder, and these have to render on a host that never
 * installed it. Where that module *is* installed, its picker hands out exactly
 * this — a URL to paste.
 *
 * The single-URL fields show what the address points at as it is typed (see
 * `./imageUrlField.tsx`). That is not the picker and does not close the gap;
 * it only means a wrong address is caught in the panel rather than on the
 * published page. `Gallery` keeps a plain textarea: its field is a *list*, and
 * a strip of thumbnails is a different control rather than the same one with a
 * picture under it.
 */

import type { ComponentConfig } from '@puckeditor/core';

import { imageUrlField } from './imageUrlField';
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
    // A URL, still — see `./imageUrlField.tsx` and the README's known gaps.
    // The field shows what the address points at, so a typo is caught where it
    // was made rather than on the published page.
    url: imageUrlField('Image URL'),
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

export interface ComparisonProps {
  beforeUrl: string;
  beforeLabel: string;
  afterUrl: string;
  afterLabel: string;
  caption: string;
}

/**
 * Two pictures of the same thing, side by side.
 *
 * Its own block rather than a two-column Gallery because the labels are the
 * content: a before-and-after nobody can tell the order of shows a change
 * without saying which way it went. They stay side by side on a phone rather
 * than stacking — a comparison a reader has to scroll between is one they have
 * to hold in their head instead of seeing.
 *
 * Not a drag-the-handle slider. That hides half of each frame behind an
 * interaction, and a reader who never touches it sees neither picture whole.
 */
export const ComparisonBlock: ComponentConfig<ComparisonProps> = {
  label: 'Before / after',
  fields: {
    beforeUrl: imageUrlField('Before — image URL'),
    beforeLabel: { type: 'text', label: 'Before — label' },
    afterUrl: imageUrlField('After — image URL'),
    afterLabel: { type: 'text', label: 'After — label' },
    caption: { type: 'text', label: 'Caption (optional)' },
  },
  defaultProps: {
    beforeUrl: '',
    beforeLabel: 'Before',
    afterUrl: '',
    afterLabel: 'After',
    caption: '',
  },
  render: ({ beforeUrl, beforeLabel, afterUrl, afterLabel, caption }) => {
    // Both or neither: one half of a comparison is just an image, and the
    // reader would be told it is a "before" with nothing to compare it to.
    if (!beforeUrl || !afterUrl) return <></>;
    return (
      <figure className="my-8">
        <div className="grid grid-cols-2 gap-3">
          {[
            { url: beforeUrl, label: beforeLabel },
            { url: afterUrl, label: afterLabel },
          ].map(({ url, label }) => (
            <figure key={url} className="m-0">
              <img src={url} alt={label} loading="lazy" className="w-full rounded-lg" />
              {label && (
                <figcaption className="mt-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {label}
                </figcaption>
              )}
            </figure>
          ))}
        </div>
        {caption && (
          <figcaption className="mt-2 text-sm text-muted-foreground">{caption}</figcaption>
        )}
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
