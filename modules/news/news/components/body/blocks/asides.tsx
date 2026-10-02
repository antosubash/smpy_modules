/**
 * Blocks that sit outside the running prose: the summary a reader takes if they
 * take nothing else, an editor's aside, and the article's sources.
 *
 * These are the three things a news story routinely sets apart from its own
 * flow, which is why they are blocks rather than paragraphs a writer styles by
 * hand.
 */

import type { ComponentConfig } from '@puckeditor/core';

import { keys, useT } from '../../../utils/i18n';

import { cells, itemKey, lines } from './lines';

export interface KeyPointsProps {
  title: string;
  items: string;
}

/** The standfirst summary box — "what you need to know".
 *
 * Its own block rather than a List with a heading above it, because it is
 * addressed to a reader who is deciding whether to read the article at all: it
 * has to survive being the only thing they look at, which means it renders as
 * one unit and cannot be half-scrolled past.
 */
export const KeyPointsBlock: ComponentConfig<KeyPointsProps> = {
  label: keys.news.blocks.key_points.label,
  fields: {
    title: { type: 'text', label: keys.news.blocks.common.heading },
    items: { type: 'textarea', label: keys.news.blocks.key_points.items },
  },
  defaultProps: { title: 'What you need to know', items: '' },
  render: ({ title, items }) => {
    const points = lines(items);
    if (points.length === 0) return <></>;
    return (
      <aside className="my-8 rounded-lg border bg-muted/40 p-5">
        {title && (
          <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {title}
          </p>
        )}
        <ul className="list-disc space-y-2 pl-5 leading-relaxed">
          {points.map((point, index) => (
            <li key={itemKey(point, index)}>{point}</li>
          ))}
        </ul>
      </aside>
    );
  },
};

export type CalloutTone = 'note' | 'important' | 'correction';

/** Full class strings, never interpolated.
 *
 * Tailwind scans this package as source text, so a class assembled at runtime
 * (`border-${tone}-300`) is a class it never sees and never emits — the failure
 * mode `host/client_app/styles.css` already carries a warning about.
 */
const TONES: Record<CalloutTone, { box: string; label: string; fallback: string }> = {
  note: {
    box: 'border-sky-300 bg-sky-50 dark:border-sky-900 dark:bg-sky-950/40',
    label: 'text-sky-900 dark:text-sky-200',
    fallback: keys.news.blocks.callout.tone_note,
  },
  important: {
    box: 'border-amber-300 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/40',
    label: 'text-amber-900 dark:text-amber-200',
    fallback: keys.news.blocks.callout.tone_important,
  },
  correction: {
    box: 'border-rose-300 bg-rose-50 dark:border-rose-900 dark:bg-rose-950/40',
    label: 'text-rose-900 dark:text-rose-200',
    fallback: keys.news.blocks.callout.tone_correction,
  },
};

export interface CalloutProps {
  tone: CalloutTone;
  title: string;
  text: string;
}

/** An aside from the desk rather than from the story.
 *
 * `correction` earns its place in the palette: a correction is an obligation a
 * publication owes its readers, and one written as an ordinary paragraph is
 * indistinguishable from the reporting it is correcting.
 */
export const CalloutBlock: ComponentConfig<CalloutProps> = {
  label: keys.news.blocks.callout.label,
  fields: {
    tone: {
      type: 'select',
      label: keys.news.blocks.callout.kind,
      options: [
        { label: keys.news.blocks.callout.kind_note, value: 'note' },
        { label: keys.news.blocks.callout.kind_important, value: 'important' },
        { label: keys.news.blocks.callout.kind_correction, value: 'correction' },
      ],
    },
    title: { type: 'text', label: keys.news.blocks.callout.title },
    text: { type: 'textarea', label: keys.news.blocks.common.text },
  },
  defaultProps: { tone: 'note', title: '', text: '' },
  // A component rather than JSX inline, because the tone's own word is
  // translated and Puck calls `render` as a plain function.
  render: ({ tone, title, text }) => <CalloutRender tone={tone} title={title} text={text} />,
};

function CalloutRender({ tone, title, text }: CalloutProps) {
  const { t } = useT();
  if (!text.trim()) return <></>;
  // A document written before a tone was added, or with one edited by hand,
  // still has to render as something.
  const style = TONES[tone] ?? TONES.note;
  return (
    <aside className={`my-8 rounded-lg border p-5 ${style.box}`}>
      <p className={`mb-1 text-xs font-semibold uppercase tracking-wide ${style.label}`}>
        {title || t(style.fallback)}
      </p>
      <p className="whitespace-pre-line leading-relaxed">{text}</p>
    </aside>
  );
}

export interface DefinitionsProps {
  title: string;
  items: string;
}

/**
 * The jargon this story cannot avoid, explained once.
 *
 * Set apart rather than parenthesised into the prose, because the two readers
 * it serves want opposite things: one needs the term explained and the other
 * already knows it and is slowed down every time the sentence stops to say so.
 * A box can be read or skipped; a parenthesis cannot.
 */
export const DefinitionsBlock: ComponentConfig<DefinitionsProps> = {
  label: keys.news.blocks.definitions.label,
  fields: {
    title: { type: 'text', label: keys.news.blocks.common.heading },
    items: { type: 'textarea', label: keys.news.blocks.definitions.items },
  },
  defaultProps: { title: 'The terms', items: '' },
  render: ({ title, items }) => {
    const entries = lines(items).map((line) => cells(line, 2));
    if (entries.length === 0) return <></>;
    return (
      <aside className="my-8 rounded-lg border p-5">
        {title && (
          <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {title}
          </p>
        )}
        <dl className="space-y-3 text-sm">
          {entries.map(([term, meaning], index) => (
            <div key={itemKey(term, index)}>
              <dt className="font-semibold">{term}</dt>
              <dd className="ml-0 leading-relaxed text-muted-foreground">{meaning}</dd>
            </div>
          ))}
        </dl>
      </aside>
    );
  },
};

export interface SourcesProps {
  title: string;
  items: string;
}

/** Where the reporting came from.
 *
 * Attribution is the one part of a story a reader may want to leave the page
 * for, so the links are real links rather than pasted URLs in a paragraph. A
 * line with no URL still renders — a book or an interview is a source that has
 * nowhere to point.
 */
export const SourcesBlock: ComponentConfig<SourcesProps> = {
  label: keys.news.blocks.sources.label,
  fields: {
    title: { type: 'text', label: keys.news.blocks.common.heading },
    items: { type: 'textarea', label: keys.news.blocks.sources.items },
  },
  defaultProps: { title: 'Sources', items: '' },
  render: ({ title, items }) => {
    const entries = lines(items).map((line) => cells(line, 2));
    if (entries.length === 0) return <></>;
    return (
      <section className="my-10 border-t pt-5 text-sm">
        {title && <h2 className="mb-3 text-sm font-semibold tracking-tight">{title}</h2>}
        <ol className="list-decimal space-y-1.5 pl-5 text-muted-foreground">
          {entries.map(([label, href], index) => (
            <li key={itemKey(label + href, index)}>
              {href ? (
                // Sources point off-site by definition, so they open away from
                // the article and carry the rel every off-site link needs.
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer nofollow"
                  className="underline underline-offset-2 hover:text-foreground"
                >
                  {label || href}
                </a>
              ) : (
                label
              )}
            </li>
          ))}
        </ol>
      </section>
    );
  },
};
