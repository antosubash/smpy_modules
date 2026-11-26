import { type Data, Puck } from '@puckeditor/core';
import '../ui/components/editor/puck-editor.css';
import { Head, router, usePage } from '@inertiajs/react';
import { BrandingHead } from '@simple-module-py/ui/components/BrandingHead';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { useMemo, useState } from 'react';

import { ConfirmDialog } from '../ui/components/ConfirmDialog';
import { BlockOutline } from '../ui/components/editor/BlockOutline';
import { NO_HEADER_ACTIONS } from '../ui/components/editor/noHeaderActions';
import { PageConflict } from '../ui/components/editor/PageConflict';
import { emptyLayoutData, getLayoutPuckConfig } from '../ui/components/layoutPuckConfig';
import { localizeConfig } from '../ui/components/localizeConfig';
import { useIsNarrow } from '../ui/hooks/useIsNarrow';
import { usePuckA11y } from '../ui/hooks/usePuckA11y';
import { useVersionedWrites } from '../ui/hooks/useVersionedWrites';
import {
  type LayoutDetail,
  type LayoutRevisionRead,
  restoreLayoutRevision,
  saveLayout,
} from '../ui/utils/api';
import { blockLabels, moveBlock, outlineOf } from '../ui/utils/blockOutline';
import { formatTimestamp } from '../ui/utils/dates';
import { keys, useT } from '../ui/utils/i18n';
import { HttpError } from '../ui/utils/request';

interface Props {
  layout: LayoutDetail;
  revisions: LayoutRevisionRead[];
}

export default function LayoutEditor() {
  const { t, locale } = useT();
  usePuckA11y();
  const props = usePage<{ props: Props }>().props as unknown as Props;
  const { layout } = props;
  const revisions = props.revisions ?? [];
  const writes = useVersionedWrites(layout.id, layout.updated_at, 'layout');

  const [headerData, setHeaderData] = useState<Data>(
    (layout.header_data as unknown as Data) ?? (emptyLayoutData as unknown as Data),
  );
  const [footerData, setFooterData] = useState<Data>(
    (layout.footer_data as unknown as Data) ?? (emptyLayoutData as unknown as Data),
  );
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  // The restore a conflict refused: Overwrite then repeats it, not a save of this screen.
  const [refusedRestore, setRefusedRestore] = useState<number | null>(null);
  const isNarrow = useIsNarrow();
  // Block labels are written as catalogue keys — see `localizeConfig` for why
  // they cannot resolve them where they are written.
  const config = useMemo(() => localizeConfig(getLayoutPuckConfig(), t), [t]);
  // The layout palette, not the page one: a header holds a different set of
  // blocks and naming them from the wrong config would miss half of them.
  const layoutLabels = blockLabels(config.components);

  const handleSave = async (overwrite = false) => {
    setBusy(true);
    setMessage(null);
    try {
      await writes.run(
        (token) =>
          saveLayout({
            header_data: headerData as unknown as Record<string, unknown>,
            footer_data: footerData as unknown as Record<string, unknown>,
            ...(overwrite ? {} : { expected_updated_at: token }),
          }),
        overwrite,
      );
      setMessage(t(keys.pagebuilder.layout.saved));
      router.reload({ only: ['revisions'] });
    } catch (e) {
      if (e instanceof HttpError && e.code === 'layout_conflict') setRefusedRestore(null);
      else {
        setMessage(e instanceof Error ? e.message : t(keys.pagebuilder.layout.save_failed));
      }
    } finally {
      setBusy(false);
    }
  };

  // Confirmation and failure both belong to the dialog on the row.
  const handleRestore = async (revisionId: number, overwrite = false) => {
    setBusy(true);
    setMessage(null);
    try {
      const restored = await writes.run(
        (token) => restoreLayoutRevision(revisionId, overwrite ? undefined : token),
        overwrite,
      );
      setRefusedRestore(null);
      setHeaderData(restored.header_data as unknown as Data);
      setFooterData(restored.footer_data as unknown as Data);
      setMessage(t(keys.pagebuilder.layout.revision_restored));
      router.reload({ only: ['revisions'] });
    } catch (e) {
      // Close the dialog so Reload and Overwrite in the banner are reachable.
      if (!(e instanceof HttpError && e.code === 'layout_conflict')) throw e;
      setRefusedRestore(revisionId);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="h-screen flex flex-col">
      {/* These editors render their own full-screen shell instead of
          AuthenticatedLayout, so nothing else mounts BrandingHead for them —
          and the preview would show the framework's default action colour
          while the published page shows the configured one.

          Known gap: this preview renders outside the design-pack root, so the
          pack's token overrides don't apply here — GCA pins its solid surfaces
          to the exact brand colour, while this preview shows the derived ramp
          step. Applying the class here would need the pack name threaded from
          the branding shared prop into both Puck instances. */}
      <BrandingHead />
      <Head title={t(keys.pagebuilder.layout.title)} />
      <div className="border-b bg-background px-4 py-2 flex items-center gap-3 flex-wrap">
        <Button variant="link" size="sm" onClick={() => router.visit('/pagebuilder')}>
          {t(keys.pagebuilder.layout.back)}
        </Button>
        <h1 className="font-medium">{t(keys.pagebuilder.layout.title)}</h1>
        <span className="text-xs text-muted-foreground">
          {t(keys.pagebuilder.layout.description)}
        </span>
        <div className="ml-auto flex gap-2">
          <Button variant="outline" size="sm" onClick={() => setShowHistory((v) => !v)}>
            {t(keys.pagebuilder.layout.history, { count: revisions.length })}
          </Button>
          <Button size="sm" disabled={busy || writes.conflict} onClick={() => void handleSave()}>
            {t(keys.pagebuilder.layout.save)}
          </Button>
        </div>
        {message && <span className="mt-1 w-full text-sm text-muted-foreground">{message}</span>}
      </div>

      {writes.conflict && (
        <PageConflict
          kind="layout"
          missing={false}
          busy={busy}
          onReload={() => router.visit('/pagebuilder/layout', { preserveState: false })}
          onOverwrite={() =>
            refusedRestore === null ? handleSave(true) : handleRestore(refusedRestore, true)
          }
        />
      )}

      {showHistory && (
        <div className="border-b bg-muted px-4 py-3 text-sm">
          {revisions.length === 0 ? (
            <p className="text-muted-foreground">{t(keys.pagebuilder.layout.no_history)}</p>
          ) : (
            <ul className="space-y-1 max-h-48 overflow-y-auto">
              {revisions.map((r) => (
                <li key={r.id} className="flex items-center justify-between gap-3 py-1">
                  <div>
                    <span className="font-medium">{t(keys.pagebuilder.layout.revision_saved)}</span>
                    <span className="ml-2 text-muted-foreground">
                      {formatTimestamp(r.created_at, locale)}
                    </span>
                    {r.created_by && (
                      <span className="ml-2 text-muted-foreground">
                        {t(keys.pagebuilder.layout.revision_by, { author: r.created_by })}
                      </span>
                    )}
                    {r.note && (
                      <div className="mt-0.5">
                        {t(keys.pagebuilder.layout.revision_note, { note: r.note })}
                      </div>
                    )}
                  </div>
                  <ConfirmDialog
                    trigger={
                      <Button
                        type="button"
                        variant="link"
                        size="sm"
                        className="h-auto p-0"
                        disabled={busy || writes.conflict}
                      >
                        {t(keys.pagebuilder.layout.restore)}
                      </Button>
                    }
                    title={t(keys.pagebuilder.layout.restore_title)}
                    description={t(keys.pagebuilder.layout.restore_description, {
                      when: formatTimestamp(r.created_at, locale),
                    })}
                    confirmLabel={t(keys.pagebuilder.layout.restore)}
                    onConfirm={() => handleRestore(r.id)}
                  />
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {isNarrow ? (
        // Two stacked drag canvases at phone width is the page editor's problem
        // twice over: each gets half a short screen. The outlines fit, and
        // reordering the header's links is the edit most likely to be wanted
        // from a phone anyway.
        <div className="flex-1 min-h-0 overflow-auto">
          <div className="mx-auto flex max-w-2xl flex-col gap-5 p-4">
            <p className="rounded-lg border bg-muted/40 p-4 text-sm text-muted-foreground">
              {t(keys.pagebuilder.layout.narrow_hint)}
            </p>
            <section data-testid="layout-header-slot">
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {t(keys.pagebuilder.layout.header)}
              </h2>
              <BlockOutline
                entries={outlineOf(headerData, layoutLabels)}
                label={t(keys.pagebuilder.layout.header_outline)}
                disabled={busy}
                emptyHint={t(keys.pagebuilder.layout.header_empty)}
                onMove={(index, direction) =>
                  setHeaderData(moveBlock(headerData, index, direction))
                }
              />
            </section>
            <section data-testid="layout-footer-slot">
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {t(keys.pagebuilder.layout.footer)}
              </h2>
              <BlockOutline
                entries={outlineOf(footerData, layoutLabels)}
                label={t(keys.pagebuilder.layout.footer_outline)}
                disabled={busy}
                emptyHint={t(keys.pagebuilder.layout.footer_empty)}
                onMove={(index, direction) =>
                  setFooterData(moveBlock(footerData, index, direction))
                }
              />
            </section>
          </div>
        </div>
      ) : (
        // Each editor fills its half and no more: Puck defaults to 100dvh, so the
        // header's editor ran under the footer's, whose toolbar then took the
        // clicks meant for the header's inspector (#237).
        <div className="flex-1 min-h-0 grid grid-rows-2 divide-y overflow-hidden">
          <section
            className="min-h-0 flex flex-col overflow-hidden"
            data-testid="layout-header-slot"
          >
            <div className="border-b bg-muted px-4 py-1 text-xs uppercase tracking-wide text-muted-foreground">
              {t(keys.pagebuilder.layout.header)}
            </div>
            <div className="flex-1 min-h-0">
              <Puck
                config={config}
                data={headerData}
                height="100%"
                iframe={{ enabled: false }}
                onChange={setHeaderData}
                overrides={NO_HEADER_ACTIONS}
              />
            </div>
          </section>
          <section
            className="min-h-0 flex flex-col overflow-hidden"
            data-testid="layout-footer-slot"
          >
            <div className="border-b bg-muted px-4 py-1 text-xs uppercase tracking-wide text-muted-foreground">
              {t(keys.pagebuilder.layout.footer)}
            </div>
            <div className="flex-1 min-h-0">
              <Puck
                config={config}
                data={footerData}
                height="100%"
                iframe={{ enabled: false }}
                onChange={setFooterData}
                overrides={NO_HEADER_ACTIONS}
              />
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
