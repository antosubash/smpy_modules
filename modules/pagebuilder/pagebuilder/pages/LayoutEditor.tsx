import { type Data, Puck } from '@measured/puck';
import '@measured/puck/puck.css';
import { router, usePage } from '@inertiajs/react';
import { BrandingHead } from '@simple-module-py/ui/components/BrandingHead';
import { useState } from 'react';

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

  const handleRestore = async (revisionId: number) => {
    if (!confirm('Restore the layout from this revision?')) return;
    setBusy(true);
    setMessage(null);
    try {
      const restored = await restoreLayoutRevision(revisionId);
      setHeaderData(restored.header_data as unknown as Data);
      setFooterData(restored.footer_data as unknown as Data);
      setMessage('Revision restored.');
      router.reload({ only: ['revisions'] });
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Restore failed');
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
      <div className="border-b bg-white px-4 py-2 flex items-center gap-3 flex-wrap">
        <button
          type="button"
          onClick={() => router.visit('/pagebuilder')}
          className="text-gray-600 hover:underline text-sm"
        >
          ← All pages
        </button>
        <h1 className="font-medium">Site layout</h1>
        <span className="text-xs text-gray-500">
          Header + footer rendered on every published page.
        </span>
        <div className="ml-auto flex gap-2">
          <button
            type="button"
            onClick={() => setShowHistory((v) => !v)}
            className="px-3 py-1 text-sm rounded border hover:bg-gray-50"
          >
            History ({revisions.length})
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={handleSave}
            className="px-3 py-1 text-sm rounded bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50"
          >
            Save layout
          </button>
        </div>
        {message && <span className="w-full text-sm text-gray-600 mt-1">{message}</span>}
      </div>

      {showHistory && (
        <div className="border-b bg-gray-50 px-4 py-3 text-sm">
          {revisions.length === 0 ? (
            <p className="text-gray-500">No history yet. Save once to record one.</p>
          ) : (
            <ul className="space-y-1 max-h-48 overflow-y-auto">
              {revisions.map((r) => (
                <li key={r.id} className="flex items-center justify-between gap-3 py-1">
                  <div>
                    <span className="font-medium">Saved</span>
                    <span className="text-gray-500 ml-2">
                      {new Date(r.created_at).toLocaleString()}
                    </span>
                    {r.created_by && <span className="text-gray-500 ml-2">by {r.created_by}</span>}
                    {r.note && <div className="text-gray-800 mt-0.5">Note: {r.note}</div>}
                  </div>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => handleRestore(r.id)}
                    className="text-blue-600 hover:underline disabled:opacity-50"
                  >
                    Restore
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="flex-1 min-h-0 grid grid-rows-2 divide-y">
        <section className="min-h-0 flex flex-col" data-testid="layout-header-slot">
          <div className="px-4 py-1 text-xs uppercase tracking-wide text-gray-500 bg-gray-50 border-b">
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
          <div className="px-4 py-1 text-xs uppercase tracking-wide text-gray-500 bg-gray-50 border-b">
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
