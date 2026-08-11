import { type Data, Puck } from '@puckeditor/core';
import '@puckeditor/core/puck.css';
import { router, usePage } from '@inertiajs/react';
import { BrandingHead } from '@simple-module-py/ui/components/BrandingHead';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { useState } from 'react';

import { ConfirmDialog } from '../components/ConfirmDialog';
import { emptyLayoutData, getLayoutPuckConfig } from '../components/layoutPuckConfig';
import {
  type LayoutDetail,
  type LayoutRevisionRead,
  restoreLayoutRevision,
  saveLayout,
} from '../utils/api';

interface Props {
  layout: LayoutDetail;
  revisions: LayoutRevisionRead[];
}

export default function LayoutEditor() {
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

  const handleSave = async () => {
    setBusy(true);
    setMessage(null);
    try {
      await saveLayout({
        header_data: headerData as unknown as Record<string, unknown>,
        footer_data: footerData as unknown as Record<string, unknown>,
      });
      setMessage('Layout saved. New pages and reloads will see the change.');
      router.reload({ only: ['revisions'] });
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Save failed');
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
      setMessage('Revision restored.');
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
          ← All pages
        </Button>
        <h1 className="font-medium">Site layout</h1>
        <span className="text-xs text-muted-foreground">
          Header + footer rendered on every published page.
        </span>
        <div className="ml-auto flex gap-2">
          <Button variant="outline" size="sm" onClick={() => setShowHistory((v) => !v)}>
            History ({revisions.length})
          </Button>
          <Button size="sm" disabled={busy} onClick={handleSave}>
            Save layout
          </Button>
        </div>
        {message && <span className="mt-1 w-full text-sm text-muted-foreground">{message}</span>}
      </div>

      {showHistory && (
        <div className="border-b bg-muted px-4 py-3 text-sm">
          {revisions.length === 0 ? (
            <p className="text-muted-foreground">No history yet. Save once to record one.</p>
          ) : (
            <ul className="space-y-1 max-h-48 overflow-y-auto">
              {revisions.map((r) => (
                <li key={r.id} className="flex items-center justify-between gap-3 py-1">
                  <div>
                    <span className="font-medium">Saved</span>
                    <span className="ml-2 text-muted-foreground">
                      {new Date(r.created_at).toLocaleString()}
                    </span>
                    {r.created_by && (
                      <span className="ml-2 text-muted-foreground">by {r.created_by}</span>
                    )}
                    {r.note && <div className="mt-0.5">Note: {r.note}</div>}
                  </div>
                  <ConfirmDialog
                    trigger={
                      <Button type="button" variant="link" size="sm" className="h-auto p-0">
                        Restore
                      </Button>
                    }
                    title="Restore this layout revision?"
                    description={`The header and footer in this editor are replaced by the version saved ${new Date(r.created_at).toLocaleString()}. The layout is shared by every published page, so saving afterwards changes all of them.`}
                    confirmLabel="Restore"
                    onConfirm={() => handleRestore(r.id)}
                  />
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="flex-1 min-h-0 grid grid-rows-2 divide-y">
        <section className="min-h-0 flex flex-col" data-testid="layout-header-slot">
          <div className="border-b bg-muted px-4 py-1 text-xs uppercase tracking-wide text-muted-foreground">
            Header
          </div>
          <div className="flex-1 min-h-0">
            <Puck
              config={getLayoutPuckConfig()}
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
            Footer
          </div>
          <div className="flex-1 min-h-0">
            <Puck
              config={getLayoutPuckConfig()}
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
    </div>
  );
}
