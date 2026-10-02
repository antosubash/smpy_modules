/**
 * Blocks for the parts of a story that are not sentences: a table of figures,
 * a command or payload worth quoting exactly, and a sequence of dated events.
 */

import type { ComponentConfig } from '@puckeditor/core';

import { cells, itemKey, lines, row } from './lines';

export interface TableProps {
  rows: string;
  header: boolean;
  caption: string;
}

/**
 * A table, typed one row per line with `|` between cells.
 *
 * Rows are not padded to a common width: a short row renders short rather than
 * gaining blank cells, because a table that quietly reshapes what was typed is
 * harder to correct than one that looks wrong.
 */
export const TableBlock: ComponentConfig<TableProps> = {
  label: 'Table',
  fields: {
    rows: { type: 'textarea', label: 'One row per line, cells split by |' },
    header: {
      type: 'radio',
      label: 'First row',
      options: [
        { label: 'Is a header', value: true },
        { label: 'Is data', value: false },
      ],
    },
    caption: { type: 'text', label: 'Caption (optional)' },
  },
  defaultProps: { rows: '', header: true, caption: '' },
  render: ({ rows, header, caption }) => {
    const parsed = lines(rows).map(row);
    if (parsed.length === 0) return <></>;
    const head = header ? parsed[0] : null;
    const body = header ? parsed.slice(1) : parsed;
    return (
      <figure className="my-8">
        {/* The article column is narrow prose; a table wide enough to need it
            scrolls inside its own box rather than pushing the whole story
            sideways. */}
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            {head && (
              <thead>
                <tr>
                  {head.map((cell, index) => (
                    <th
                      key={itemKey(cell, index)}
                      scope="col"
                      className="border-b-2 px-3 py-2 text-left font-semibold"
                    >
                      {cell}
                    </th>
                  ))}
                </tr>
              </thead>
            )}
            <tbody>
              {body.map((line, lineIndex) => (
                <tr key={itemKey(line.join('|'), lineIndex)}>
                  {line.map((cell, index) => (
                    <td key={itemKey(cell, index)} className="border-b px-3 py-2 tabular-nums">
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {caption && (
          <figcaption className="mt-2 text-sm text-muted-foreground">{caption}</figcaption>
        )}
      </figure>
    );
  },
};

export interface CodeProps {
  code: string;
  language: string;
  caption: string;
}

/**
 * A verbatim block — a command, a payload, a log line.
 *
 * Not syntax-highlighted, and deliberately: highlighting means a highlighter,
 * and this module renders on the public article page of a host that may have
 * installed nothing else. `language` is a label for the reader, not a hint to a
 * parser, which is why it is free text rather than a select of the languages
 * some bundled grammar happens to support.
 */
export const CodeBlock: ComponentConfig<CodeProps> = {
  label: 'Code',
  fields: {
    code: { type: 'textarea', label: 'Code' },
    language: { type: 'text', label: 'Language label (optional)' },
    caption: { type: 'text', label: 'Caption (optional)' },
  },
  defaultProps: { code: '', language: '', caption: '' },
  render: ({ code, language, caption }) => {
    if (!code.trim()) return <></>;
    return (
      <figure className="my-8">
        <div className="overflow-hidden rounded-lg border bg-muted/60">
          {language && (
            <p className="border-b px-4 py-1.5 font-mono text-xs text-muted-foreground">
              {language}
            </p>
          )}
          <pre className="overflow-x-auto px-4 py-3 text-sm leading-relaxed">
            <code>{code}</code>
          </pre>
        </div>
        {caption && (
          <figcaption className="mt-2 text-sm text-muted-foreground">{caption}</figcaption>
        )}
      </figure>
    );
  },
};

export interface FactsProps {
  title: string;
  items: string;
}

/**
 * The figures a story turns on, pulled out of the prose.
 *
 * Not a Table with one row: a table is for numbers a reader compares against
 * each other, and these are numbers a reader is meant to remember. The label
 * sits under the figure rather than beside it for the same reason — the figure
 * is what carries, and the label only says what it counts.
 */
export const FactsBlock: ComponentConfig<FactsProps> = {
  label: 'Key figures',
  fields: {
    title: { type: 'text', label: 'Heading (optional)' },
    items: { type: 'textarea', label: 'One per line — "21 | sensors installed"' },
  },
  defaultProps: { title: '', items: '' },
  render: ({ title, items }) => {
    const entries = lines(items).map((line) => cells(line, 2));
    if (entries.length === 0) return <></>;
    return (
      <section className="my-8">
        {title && (
          <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {title}
          </p>
        )}
        {/* Wraps rather than fixing a column count: three figures on a phone
            are three unreadable slivers if they are forced to share a row. */}
        <dl className="flex flex-wrap gap-x-10 gap-y-5">
          {entries.map(([figure, label], index) => (
            <div key={itemKey(figure + label, index)}>
              <dt className="text-3xl font-semibold tracking-tight tabular-nums">{figure}</dt>
              <dd className="ml-0 mt-0.5 text-sm text-muted-foreground">{label}</dd>
            </div>
          ))}
        </dl>
      </section>
    );
  },
};

export interface TimelineProps {
  title: string;
  items: string;
}

/**
 * How the story unfolded: a dated sequence.
 *
 * The date is free text rather than a date field. Reporting deals in "March
 * 2024", "the following morning" and "some time before 2019", and a control
 * that demanded a calendar day would force a writer to invent precision the
 * reporting does not have.
 */
export const TimelineBlock: ComponentConfig<TimelineProps> = {
  label: 'Timeline',
  fields: {
    title: { type: 'text', label: 'Heading (optional)' },
    items: { type: 'textarea', label: 'One per line — "when | what happened"' },
  },
  defaultProps: { title: '', items: '' },
  render: ({ title, items }) => {
    const entries = lines(items).map((line) => cells(line, 2));
    if (entries.length === 0) return <></>;
    return (
      <section className="my-8">
        {title && <h2 className="mb-4 text-xl font-semibold tracking-tight">{title}</h2>}
        <ol className="space-y-4 border-l-2 pl-5">
          {entries.map(([when, what], index) => (
            <li key={itemKey(when + what, index)} className="relative">
              {/* The marker sits on the rule the list is hung from, so the
                  sequence reads as a line rather than as an indented list. */}
              <span
                aria-hidden="true"
                className="absolute -left-[1.6rem] top-2 size-2.5 rounded-full bg-primary"
              />
              {when && (
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {when}
                </p>
              )}
              <p className="leading-relaxed">{what}</p>
            </li>
          ))}
        </ol>
      </section>
    );
  },
};
