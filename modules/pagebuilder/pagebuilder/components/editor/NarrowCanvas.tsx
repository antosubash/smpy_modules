import type { Data } from '@puckeditor/core';

import { blockLabels, moveBlock, outlineOf } from '../../utils/blockOutline';
import { getPuckConfig } from '../puckConfig';
import { BlockOutline } from './BlockOutline';

interface Props {
  data: Data;
  onChange: (next: Data) => void;
  /** The draft preview route. Null before the page has been saved once. */
  previewUrl: string | null;
  busy?: boolean;
}

/**
 * What the page editor offers below 900px, in place of the drag canvas.
 *
 * The canvas is not shrunk, it is withheld: a drag surface at phone width is a
 * surface where every drop lands somewhere you did not mean. Everything that
 * does not need width stays — preview, reorder, schedule and publish — so the
 * screen is still worth opening rather than a wall saying "come back later".
 */
export function NarrowCanvas({ data, onChange, previewUrl, busy }: Props) {
  const entries = outlineOf(data, blockLabels(getPuckConfig().components));

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-5 p-4">
      <section className="rounded-lg border bg-muted/40 p-4">
        <h2 className="text-sm font-semibold">Preview and publish here, edit on a larger screen</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Drag-and-drop layout needs width, so the canvas is read-only at this size. You can still
          preview the draft, reorder blocks below, schedule and publish.
        </p>
        {previewUrl && (
          <a
            href={previewUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-3 inline-flex h-9 items-center rounded-md border bg-background px-4 text-sm font-medium hover:bg-accent"
          >
            Preview the draft
          </a>
        )}
      </section>

      <section>
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Outline
        </h2>
        <BlockOutline
          entries={entries}
          label="Page outline"
          disabled={busy}
          onMove={(index, direction) => onChange(moveBlock(data, index, direction))}
        />
      </section>
    </div>
  );
}
