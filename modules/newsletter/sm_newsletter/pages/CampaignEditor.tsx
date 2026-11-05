import { Head, router, usePage } from '@inertiajs/react';
import { type Overrides, type Permissions, Puck } from '@puckeditor/core';
import '../ui/components/editor/puck-editor.css';
import { BrandingHead } from '@simple-module-py/ui/components/BrandingHead';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Skeleton } from '@simple-module-py/ui/components/ui/skeleton';
import { useEffect, useMemo, useState } from 'react';

import { campaignsUrl } from '../ui/components/campaigns/urls';
import { CampaignMeta } from '../ui/components/editor/CampaignMeta';
import { type EditorTab, EditorTabs } from '../ui/components/editor/EditorTabs';
import { EditorActionsContext } from '../ui/components/editor/editorActions';
import { localizeConfig } from '../ui/components/editor/localizeConfig';
import { PreviewPane } from '../ui/components/editor/PreviewPane';
import { buildConfig, type Capabilities } from '../ui/components/editor/puckConfig';
import { type EditorStatus, useCampaignEditor } from '../ui/hooks/useCampaignEditor';
import { normalizeBody } from '../ui/utils/bodyDraft';
import { keys, useT } from '../ui/utils/i18n';
import { fromPuckData } from '../ui/utils/puckData';

/** The props `web/endpoints/views.py` `campaign_editor` renders. */
interface EditorProps {
  campaign_id: number;
  can_edit?: boolean;
  can_send?: boolean;
  capabilities?: Capabilities;
  public_base_url_set?: boolean;
  max_test_recipients?: number;
}

/** Puck with nothing a viewer could change: no edit, insert, move, copy or delete. */
const READ_ONLY: Partial<Permissions> = {
  drag: false,
  edit: false,
  insert: false,
  delete: false,
  duplicate: false,
};

const copy = keys.newsletter.editor;

/** Test sends are capped at five server-side; the page prop says what this host allows. */
const DEFAULT_MAX_TEST_RECIPIENTS = 5;

const STATUS_LABEL: Record<EditorStatus, string | null> = {
  idle: null,
  saving: copy.status.saving,
  saved: copy.status.saved,
  stale: copy.status.stale,
  error: copy.status.error,
};

/** A campaign's email, written in newsletter's own Puck config.
 *
 * Its own full-height shell rather than `AuthenticatedLayout`, like news'
 * article body: Puck wants the whole viewport. The email is read-only for a
 * viewer without `can_edit`, and for everyone once the campaign is no longer a
 * draft (the server would refuse the write anyway).
 */
export default function CampaignEditor() {
  const { t } = useT();
  const props = usePage().props as unknown as EditorProps;
  const editor = useCampaignEditor(props.campaign_id);
  const { campaign } = editor;
  const news = props.capabilities?.news === true;
  const pagebuilder = props.capabilities?.pagebuilder === true;
  const config = useMemo(
    () => localizeConfig(buildConfig({ news, pagebuilder }), t),
    [news, pagebuilder, t],
  );
  const actions = useMemo(() => ({ refresh: editor.refresh }), [editor.refresh]);
  const [tab, setTab] = useState<EditorTab>('edit');
  const previewBody = useMemo(() => normalizeBody(fromPuckData(editor.data)), [editor.data]);
  const isDraft = campaign?.status === 'draft';
  const readOnly = props.can_edit !== true || !isDraft || editor.status === 'stale';

  // Stable: Puck treats a new override as a new component and remounts what
  // it wraps, which would drop focus from the field being typed in.
  const overrides = useMemo<Partial<Overrides>>(
    () => ({
      // Puck's own "Publish" would do nothing here: the email autosaves, and
      // sending is a separate step.
      headerActions: () => <></>,
      // The root has no fields (the details are above the canvas), so an empty
      // panel would show with nothing selected; say what to do instead.
      fields: ({ children, itemSelector }) =>
        itemSelector ? (
          <>{children}</>
        ) : (
          <p className="p-4 text-sm text-muted-foreground">{t(copy.select_a_block)}</p>
        ),
    }),
    [t],
  );

  // Closing or reloading the tab while an edit is not on the server — inside
  // the debounce, after a failed save, or held back by an unfinished block —
  // asks first, as news, pagebuilder and records do. An in-app visit unmounts
  // the hook, which flushes what can be saved.
  useEffect(() => {
    if (!editor.dirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [editor.dirty]);

  const statusKey = STATUS_LABEL[editor.status];
  const title = campaign ? campaign.name || t(copy.untitled) : t(copy.fallback_title);

  return (
    <div className="flex h-screen flex-col">
      {/* Outside AuthenticatedLayout nothing else mounts the branding colours. */}
      <BrandingHead />
      <Head title={title} />

      <header className="flex flex-wrap items-center gap-3 border-b px-4 py-2">
        <Button variant="ghost" size="sm" onClick={() => router.visit(campaignsUrl)}>
          {t(copy.back)}
        </Button>
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">{title}</p>
          {campaign && (
            <p className="truncate text-xs text-muted-foreground">
              {t(copy.list, { list: campaign.list_type_key })}
            </p>
          )}
        </div>
        {campaign && (
          <>
            <EditorTabs
              tab={tab}
              onTab={setTab}
              campaignId={campaign.id}
              canSend={props.can_send === true}
              maxRecipients={props.max_test_recipients ?? DEFAULT_MAX_TEST_RECIPIENTS}
              baseUrlMissing={props.public_base_url_set === false}
              flush={editor.flush}
              incomplete={editor.incomplete}
            />
          </>
        )}
        <span className="text-xs text-muted-foreground" aria-live="polite">
          {statusKey ? t(statusKey) : ''}
        </span>
      </header>

      {editor.error && (
        <div
          role="alert"
          className="flex items-center gap-3 border-b bg-destructive/10 px-4 py-2 text-sm text-destructive"
        >
          <p className="min-w-0 flex-1">{editor.error}</p>
          {editor.status === 'stale' && (
            <Button size="sm" variant="outline" onClick={() => void editor.reload()}>
              {t(copy.reload)}
            </Button>
          )}
        </div>
      )}
      {campaign && readOnly && editor.status !== 'stale' && (
        <p className="border-b bg-muted px-4 py-2 text-sm text-muted-foreground">
          {t(isDraft ? copy.read_only : copy.not_draft)}
        </p>
      )}
      {editor.incomplete && !readOnly && (
        <p className="border-b bg-amber-50 px-4 py-2 text-sm text-amber-900">
          {t(copy.incomplete)}
        </p>
      )}

      {campaign ? (
        <>
          <CampaignMeta
            key={editor.reloadKey}
            campaign={campaign}
            readOnly={readOnly}
            onChange={editor.saveMeta}
          />
          {tab === 'preview' && (
            <PreviewPane
              id={campaign.id}
              editable={!readOnly}
              subject={campaign.subject}
              preheader={campaign.preheader}
              body={previewBody}
            />
          )}
          <div className={tab === 'edit' ? 'min-h-0 flex-1' : 'hidden'}>
            <EditorActionsContext.Provider value={actions}>
              <Puck
                key={editor.reloadKey}
                config={config}
                data={editor.data}
                permissions={readOnly ? READ_ONLY : undefined}
                overrides={overrides}
                iframe={{ enabled: true }}
                onChange={readOnly ? undefined : editor.onChange}
              />
            </EditorActionsContext.Provider>
          </div>
        </>
      ) : (
        !editor.error && (
          <div role="status" aria-label={t(copy.loading)} className="space-y-2 p-4">
            <Skeleton className="h-8 w-1/2" />
            <Skeleton className="h-40 w-full" />
          </div>
        )
      )}
    </div>
  );
}
