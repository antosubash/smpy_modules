/**
 * A contents list for a long article.
 *
 * The second block in this palette that reads something other than its own
 * props, and the first that reads the *document*: it lists the article's
 * `Heading` blocks and links to them. See `./outline.ts` for how it can, and
 * why the anchors are derived there rather than here.
 *
 * It earns its place on the same terms as the rest of the set — a newsroom
 * already puts one at the head of an explainer, and without a block the only
 * way to write one is a hand-typed List whose links break the moment a section
 * is renamed or moved.
 *
 * Its own file rather than a sixth block in `asides.tsx` for the reason
 * `related.tsx` is one: the blocks that reach outside themselves are the ones
 * with something to explain, and the file that holds the plain ones is at the
 * size cap already.
 */

import type { ComponentConfig } from '@puckeditor/core';

import { groupOutline, type OutlineEntry, outlineFromMetadata } from './outline';

export interface ContentsProps {
  title: string;
  /** '2' lists sections only; '3' nests sub-sections under them. */
  depth: '2' | '3';
}

/**
 * Below this the list is not worth drawing.
 *
 * A contents list of one entry tells a reader nothing they did not get from
 * scrolling, and puts a box between them and the first paragraph to do it.
 */
const MIN_SECTIONS = 2;

export function ContentsRender({
  title,
  depth,
  outline,
  isEditing,
}: ContentsProps & { outline: OutlineEntry[]; isEditing: boolean }) {
  const sections = groupOutline(outline, depth === '3');

  if (sections.length < MIN_SECTIONS) {
    // On the canvas, rendering nothing is indistinguishable from a block that
    // failed to load — and a writer who has just dropped this in has, by
    // definition, not written the headings yet. A reader gets the silence.
    if (!isEditing) return <></>;
    return (
      <p className="my-8 rounded-lg border border-dashed p-5 text-sm text-muted-foreground">
        Contents lists this article's section headings. Add at least {MIN_SECTIONS} Heading blocks
        and they appear here, and on the published page.
      </p>
    );
  }

  return (
    <nav aria-label={title || 'Contents'} className="my-8 rounded-lg border bg-muted/40 p-5">
      {title && (
        <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {title}
        </p>
      )}
      {/* Ordered, and nested where the article nests: the list is a map of the
          document, so it should have the document's shape rather than be
          flattened into one column of links. */}
      <ol className="list-decimal space-y-1.5 pl-5">
        {sections.map(({ entry, children }) => (
          <li key={entry.anchor}>
            <a href={`#${entry.anchor}`} className="underline underline-offset-2">
              {entry.text}
            </a>
            {children.length > 0 && (
              <ol className="mt-1.5 list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                {children.map((child) => (
                  <li key={child.anchor}>
                    <a href={`#${child.anchor}`} className="underline underline-offset-2">
                      {child.text}
                    </a>
                  </li>
                ))}
              </ol>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}

export const ContentsBlock: ComponentConfig<ContentsProps> = {
  label: 'Contents',
  fields: {
    title: { type: 'text', label: 'Heading' },
    depth: {
      type: 'select',
      label: 'How deep',
      options: [
        { label: 'Sections only', value: '2' },
        { label: 'Sections and sub-sections', value: '3' },
      ],
    },
  },
  defaultProps: { title: 'In this article', depth: '2' },
  render: ({ depth, puck, title }) => (
    <ContentsRender
      title={title}
      depth={depth}
      outline={outlineFromMetadata(puck?.metadata)}
      isEditing={puck?.isEditing ?? false}
    />
  ),
};
