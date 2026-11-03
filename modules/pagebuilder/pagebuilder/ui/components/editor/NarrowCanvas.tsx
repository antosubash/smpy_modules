import type { Data } from '@puckeditor/core';
import { useMemo } from 'react';

import { blockLabels, moveBlock, outlineOf } from '../../utils/blockOutline';
import { keys, useT } from '../../utils/i18n';
import { localizeConfig } from '../localizeConfig';
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
  const { t } = useT();
  // Through `localizeConfig` rather than the raw config: a block's label is a
  // catalogue key until something resolves it, and an unresolved one would
  // name every row in the outline after its own key.
  const labels = useMemo(() => blockLabels(localizeConfig(getPuckConfig(), t).components), [t]);
  const entries = outlineOf(data, labels);

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-5 p-4">
      <section className="rounded-lg border bg-muted/40 p-4">
        <h2 className="text-sm font-semibold">{t(keys.pagebuilder.narrow.title)}</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {t(keys.pagebuilder.narrow.description)}
        </p>
        {previewUrl && (
          <a
            href={previewUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-3 inline-flex h-9 items-center rounded-md border bg-background px-4 text-sm font-medium hover:bg-accent"
          >
            {t(keys.pagebuilder.narrow.preview)}
          </a>
        )}
      </section>

      <section>
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {t(keys.pagebuilder.narrow.outline)}
        </h2>
        <BlockOutline
          entries={entries}
          label={t(keys.pagebuilder.narrow.page_outline)}
          disabled={busy}
          onMove={(index, direction) => onChange(moveBlock(data, index, direction))}
        />
      </section>
    </div>
  );
}
