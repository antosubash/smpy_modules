import { type Data, Puck } from '@puckeditor/core';
import '@puckeditor/core/puck.css';
import { router, usePage } from '@inertiajs/react';
import { BrandingHead } from '@simple-module-py/ui/components/BrandingHead';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { useMemo, useState } from 'react';

import { ConfirmDialog } from '../components/ConfirmDialog';
import { BlockOutline } from '../components/editor/BlockOutline';
import { emptyLayoutData, getLayoutPuckConfig } from '../components/layoutPuckConfig';
import { localizeConfig } from '../components/localizeConfig';
import { useIsNarrow } from '../hooks/useIsNarrow';
import {
  type LayoutDetail,
  type LayoutRevisionRead,
  restoreLayoutRevision,
  saveLayout,
} from '../utils/api';
import { blockLabels, moveBlock, outlineOf } from '../utils/blockOutline';
import { keys, useT } from '../utils/i18n';

interface Props {
  layout: LayoutDetail;
  revisions: LayoutRevisionRead[];
}

export default function LayoutEditor() {
  const { t } = useT();
  const props = usePage<{ props: Props }>().props as unknown as Props;
  const { layout } = props;
  const revisions = props.revisions ?? [];

  const [headerData, setHeaderData] = useState<Data>(
    (layout.header_data as unknown as Data) ?? (emptyLayoutData as unknown as Data),
  );
  const [footerData, setFooterData] = useState<Data>(
    (layout.footer_data as unknown as Data) ?? (emptyLayoutData as unknown as Data),
  );
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const isNarrow = useIsNarrow();
  // Block labels are written as catalogue keys — see `localizeConfig` for why
  // they cannot resolve them where they are written.
  const config = useMemo(() => localizeConfig(getLayoutPuckConfig(), t), [t]);
  // The layout palette, not the page one: a header holds a different set of
  // blocks and naming them from the wrong config would miss half of them.
  const layoutLabels = blockLabels(config.components);

  const handleSave = async () => {
    setBusy(true);
    setMessage(null);
    try {
      await saveLayout({
        header_data: headerData as unknown as Record<string, unknown>,
        footer_data: footerData as unknown as Record<string, unknown>,
      });
      setMessage(t(keys.pagebuilder.layout.saved));
      router.reload({ only: ['revisions'] });
    } catch (e) {
      setMessage(e instanceof Error ? e.message : t(keys.pagebuilder.layout.save_failed));
    } finally {
      setBusy(false);
    }
  };

  // Confirmation and failure both belong to the dialog on the row.
  const handleRestore = async (revisionId: number) => {
    setBusy(true);
    setMessage(null);
    try {
      const restored = await restoreLayoutRevision(revisionId);
      setHeaderData(restored.header_data as unknown as Data);
      setFooterData(restored.footer_data as unknown as Data);
      setMessage(t(keys.pagebuilder.layout.revision_restored));
      router.reload({ only: ['revisions'] });
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
          <Button size="sm" disabled={busy} onClick={handleSave}>
            {t(keys.pagebuilder.layout.save)}
          </Button>
        </div>
        {message && <span className="mt-1 w-full text-sm text-muted-foreground">{message}</span>}
      </div>

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
                      {new Date(r.created_at).toLocaleString()}
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
                      <Button type="button" variant="link" size="sm" className="h-auto p-0">
                        {t(keys.pagebuilder.layout.restore)}
                      </Button>
                    }
                    title={t(keys.pagebuilder.layout.restore_title)}
                    description={t(keys.pagebuilder.layout.restore_description, {
                      when: new Date(r.created_at).toLocaleString(),
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
        <div className="flex-1 min-h-0 grid grid-rows-2 divide-y">
          <section className="min-h-0 flex flex-col" data-testid="layout-header-slot">
            <div className="border-b bg-muted px-4 py-1 text-xs uppercase tracking-wide text-muted-foreground">
              {t(keys.pagebuilder.layout.header)}
            </div>
            <div className="flex-1 min-h-0">
              <Puck
                config={config}
                data={headerData}
                iframe={{ enabled: false }}
                onChange={setHeaderData}
                onPublish={(d) => {
                  setHeaderData(d);
                  void handleSave();
                }}
              />
            </div>
          </section>
          <section className="min-h-0 flex flex-col" data-testid="layout-footer-slot">
            <div className="border-b bg-muted px-4 py-1 text-xs uppercase tracking-wide text-muted-foreground">
              {t(keys.pagebuilder.layout.footer)}
            </div>
            <div className="flex-1 min-h-0">
              <Puck
                config={config}
                data={footerData}
                iframe={{ enabled: false }}
                onChange={setFooterData}
                onPublish={(d) => {
                  setFooterData(d);
                  void handleSave();
                }}
              />
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
