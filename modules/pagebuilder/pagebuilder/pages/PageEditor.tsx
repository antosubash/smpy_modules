import { Puck, type Data } from '@measured/puck';
import '@measured/puck/puck.css';
import { router, usePage } from '@inertiajs/react';
import { useEffect, useMemo, useRef, useState } from 'react';

import { editorViewports, emptyData, puckConfig } from '../components/puckConfig';
import { DiffSummary } from '../components/DiffSummary';
import { ScheduledBadge } from '../components/ScheduledBadge';
import { StatusBadge } from '../components/StatusBadge';
import {
  approvePage,
  createPage,
  diffRevisions,
  promptAndReject,
  publishPage,
  restoreRevision,
  savePage,
  schedulePage,
  submitPage,
  unpublishPage,
  type PageDetail,
  type PageRevisionRead,
  type RevisionDiff,
  type RevisionEvent,
} from '../utils/api';
import { slugify } from '../utils/slugify';

interface Props {
  page: PageDetail | null;
  revisions: PageRevisionRead[];
}

const EVENT_LABELS: Record<RevisionEvent, string> = {
  publish: 'Published',
  unpublish: 'Unpublished',
  submit: 'Submitted for review',
  approve: 'Approved',
  reject: 'Rejected',
};

// Revision events whose ``data`` snapshot matches what /p/{slug} served.
const RESTORABLE_EVENTS: ReadonlySet<RevisionEvent> = new Set(['publish', 'approve']);

const AUTOSAVE_DEBOUNCE_MS = 2000;

/**
 * Format an ISO string (with offset, from the server) into the local
 * ``YYYY-MM-DDTHH:mm`` shape an ``<input type="datetime-local">``
 * expects. Returns ``""`` for null so the input renders empty.
 */
function toLocalInput(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/**
 * Inverse of toLocalInput: take whatever a ``datetime-local`` produced
 * (a naive local-time string) and emit an ISO string with offset that
 * round-trips through the server's UTC normalisation.
 */
function fromLocalInput(value: string | null): string | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

type SaveState = 'idle' | 'saving' | 'error';

interface EditorSnapshot {
  title: string;
  slug: string;
  metaDescription: string;
  ogImage: string;
  canonicalUrl: string;
  indexInSearch: boolean;
  jsonLdText: string;
  data: Data;
}

function snapshotKey(payload: EditorSnapshot): string {
  return JSON.stringify(payload);
}

function formatSaveLabel(
  state: SaveState,
  isDirty: boolean,
  lastSavedAt: Date | null,
  errorMessage: string | null,
): string {
  if (state === 'saving') return 'Saving…';
  if (state === 'error') return errorMessage ? `Save failed: ${errorMessage}` : 'Save failed';
  if (isDirty) return 'Unsaved changes';
  if (lastSavedAt) {
    const hh = String(lastSavedAt.getHours()).padStart(2, '0');
    const mm = String(lastSavedAt.getMinutes()).padStart(2, '0');
    return `Saved at ${hh}:${mm}`;
  }
  return 'Saved';
}

export default function PageEditor() {
  const props = usePage<{ props: Props }>().props as unknown as Props;
  const { page } = props;

  const [pageId, setPageId] = useState<number | null>(page?.id ?? null);
  const [title, setTitle] = useState(page?.title ?? 'Untitled page');
  const [slug, setSlug] = useState(page?.slug ?? '');
  const [slugTouched, setSlugTouched] = useState(Boolean(page?.slug));
  const [metaDescription, setMetaDescription] = useState(page?.meta_description ?? '');
  const [ogImage, setOgImage] = useState(page?.og_image ?? '');
  const [canonicalUrl, setCanonicalUrl] = useState(page?.canonical_url ?? '');
  const [indexInSearch, setIndexInSearch] = useState<boolean>(page?.index_in_search ?? true);
  const [jsonLdText, setJsonLdText] = useState<string>(
    page?.json_ld ? JSON.stringify(page.json_ld, null, 2) : '',
  );
  const [jsonLdError, setJsonLdError] = useState<string | null>(null);
  const [status, setStatus] = useState<PageDetail['status']>(page?.status ?? 'draft');
  // ISO 8601 strings (with offset). The native ``datetime-local`` input
  // emits *naive* values like ``"2026-05-19T09:30"`` so we adapt at the
  // boundary in toLocalInput/fromLocalInput rather than carrying two
  // representations through component state.
  const [publishAt, setPublishAt] = useState<string | null>(page?.publish_at ?? null);
  const [unpublishAt, setUnpublishAt] = useState<string | null>(page?.unpublish_at ?? null);
  const [scheduleError, setScheduleError] = useState<string | null>(null);
  // ``rejection_note`` lives on the page prop and refreshes after every
  // partial reload — no separate useState slot needed.
  const rejectionNote = page?.rejection_note ?? null;
  const [data, setData] = useState<Data>(
    (page?.draft_data as unknown as Data) || (emptyData as unknown as Data),
  );
  const revisions = props.revisions ?? [];
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [activeDiff, setActiveDiff] = useState<RevisionDiff | null>(null);
  const [diffError, setDiffError] = useState<string | null>(null);

  const effectiveSlug = slugTouched ? slug : slugify(title);

  // ``json_ld`` is omitted from the payload when the editor textarea is
  // unparseable so a malformed draft doesn't silently overwrite a good
  // saved value. The ``jsonLdError`` state surfaces the parse error
  // inline; explicit save/publish actions short-circuit earlier on it.
  const parseJsonLd = (): Record<string, unknown> | null | undefined => {
    const trimmed = jsonLdText.trim();
    if (!trimmed) return null;
    try {
      const parsed = JSON.parse(trimmed);
      if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        return undefined;
      }
      return parsed as Record<string, unknown>;
    } catch {
      return undefined;
    }
  };

  const writePayload = () => {
    const parsedLd = parseJsonLd();
    return {
      title,
      slug: effectiveSlug || slugify(title) || 'untitled',
      meta_description: metaDescription.trim() ? metaDescription.trim() : null,
      og_image: ogImage.trim() ? ogImage.trim() : null,
      canonical_url: canonicalUrl.trim() ? canonicalUrl.trim() : null,
      index_in_search: indexInSearch,
      // Only include json_ld in the payload when we have a valid parse;
      // ``undefined`` (parse error) is dropped so the server retains the
      // previously saved value.
      ...(parsedLd === undefined ? {} : { json_ld: parsedLd }),
    };
  };

  // Autosave bookkeeping. ``savedSnapshot`` is the serialized form of
  // what the server has — any divergence flips the editor into dirty
  // and arms the debounce timer. New (unsaved) pages opt out: the first
  // save creates the row + redirects, which can't sensibly happen on a
  // background timer.
  const currentSnapshotPayload: EditorSnapshot = {
    title,
    slug: effectiveSlug,
    metaDescription,
    ogImage,
    canonicalUrl,
    indexInSearch,
    jsonLdText,
    data,
  };
  // Memoize the stringify on every render — Puck ``data`` can be hundreds
  // of KB on a populated page, and the component re-renders on every
  // keystroke.
  const currentSnapshot = useMemo(
    () => snapshotKey(currentSnapshotPayload),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [title, effectiveSlug, metaDescription, ogImage, canonicalUrl, indexInSearch, jsonLdText, data],
  );

  const initialSnapshot = useMemo(
    () =>
      snapshotKey({
        title: page?.title ?? 'Untitled page',
        slug: page?.slug ?? '',
        metaDescription: page?.meta_description ?? '',
        ogImage: page?.og_image ?? '',
        canonicalUrl: page?.canonical_url ?? '',
        indexInSearch: page?.index_in_search ?? true,
        jsonLdText: page?.json_ld ? JSON.stringify(page.json_ld, null, 2) : '',
        data: (page?.draft_data as unknown as Data) || (emptyData as unknown as Data),
      }),
    // Inertia remounts on a different page id, which is the right time
    // for a fresh baseline.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const [savedSnapshot, setSavedSnapshot] = useState<string>(initialSnapshot);
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [lastSavedAt, setLastSavedAt] = useState<Date | null>(null);
  const [autosaveError, setAutosaveError] = useState<string | null>(null);

  const isDirty = currentSnapshot !== savedSnapshot;

  const markSaved = (payload: EditorSnapshot) => {
    setSavedSnapshot(snapshotKey(payload));
    setSaveState('idle');
    setLastSavedAt(new Date());
    setAutosaveError(null);
  };

  const currentMarkSavedPayload = (newData: Data): EditorSnapshot => ({
    ...currentSnapshotPayload,
    data: newData,
  });

  const handleSave = async (newData: Data) => {
    setBusy(true);
    setMessage(null);
    try {
      if (pageId === null) {
        const created = await createPage({
          ...writePayload(),
          draft_data: newData as unknown as Record<string, unknown>,
        });
        setPageId(created.id);
        setSlug(created.slug);
        setSlugTouched(true);
        setStatus(created.status);
        router.visit(`/pagebuilder/${created.id}/edit`, { preserveState: false });
      } else {
        const updated = await savePage(pageId, {
          ...writePayload(),
          draft_data: newData as unknown as Record<string, unknown>,
        });
        setStatus(updated.status);
        markSaved(currentMarkSavedPayload(newData));
        setMessage('Draft saved.');
      }
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Save failed');
    } finally {
      setBusy(false);
    }
  };

  const handlePublish = async () => {
    if (pageId === null) {
      await handleSave(data);
      return;
    }
    // Prompt returns `null` on Cancel, `''` on bare-press Enter — only
    // ``null`` should abort. An empty string means "publish, no note".
    const noteInput = window.prompt(
      'Optional message describing this publish (leave blank to skip):',
      '',
    );
    if (noteInput === null) return;
    const note = noteInput.trim() || null;
    setBusy(true);
    setMessage(null);
    try {
      await savePage(pageId, {
        ...writePayload(),
        draft_data: data as unknown as Record<string, unknown>,
      });
      markSaved(currentMarkSavedPayload(data));
      const result = await publishPage(pageId, note);
      setStatus(result.status);
      setMessage('Published.');
      router.reload({ only: ['revisions'] });
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Publish failed');
    } finally {
      setBusy(false);
    }
  };

  const handleUnpublish = async () => {
    if (pageId === null) return;
    setBusy(true);
    setMessage(null);
    try {
      const result = await unpublishPage(pageId);
      setStatus(result.status);
      setMessage('Unpublished.');
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Unpublish failed');
    } finally {
      setBusy(false);
    }
  };

  const handleSubmitForReview = async () => {
    if (pageId === null) {
      setMessage('Save a draft first.');
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      await savePage(pageId, {
        ...writePayload(),
        draft_data: data as unknown as Record<string, unknown>,
      });
      markSaved(currentMarkSavedPayload(data));
      const result = await submitPage(pageId);
      setStatus(result.status);
      setMessage('Submitted for review.');
      router.reload({ only: ['revisions', 'page'] });
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Submit failed');
    } finally {
      setBusy(false);
    }
  };

  const handleApprove = async () => {
    if (pageId === null) return;
    setBusy(true);
    setMessage(null);
    try {
      const result = await approvePage(pageId);
      setStatus(result.status);
      setMessage('Approved and published.');
      router.reload({ only: ['revisions', 'page'] });
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Approve failed');
    } finally {
      setBusy(false);
    }
  };

  const handleReject = async () => {
    if (pageId === null) return;
    setBusy(true);
    setMessage(null);
    const result = await promptAndReject(pageId);
    setBusy(false);
    if ('skipped' in result) {
      if (result.skipped !== 'cancelled') setMessage(result.skipped);
      return;
    }
    setStatus(result.status);
    setMessage('Sent back to draft.');
    router.reload({ only: ['revisions', 'page'] });
  };

  const handleSaveSchedule = async () => {
    if (pageId === null) {
      setScheduleError('Save a draft first.');
      return;
    }
    setScheduleError(null);
    const publish = fromLocalInput(publishAt);
    const unpublish = fromLocalInput(unpublishAt);
    if (publish && unpublish && publish >= unpublish) {
      setScheduleError('Unpublish time must be after publish time.');
      return;
    }
    setBusy(true);
    try {
      const updated = await schedulePage(pageId, {
        publish_at: publish,
        unpublish_at: unpublish,
      });
      setPublishAt(updated.publish_at);
      setUnpublishAt(updated.unpublish_at);
      setMessage('Schedule saved.');
    } catch (e) {
      setScheduleError(e instanceof Error ? e.message : 'Could not save schedule');
    } finally {
      setBusy(false);
    }
  };

  const handleClearSchedule = async () => {
    if (pageId === null) return;
    setBusy(true);
    setScheduleError(null);
    try {
      const updated = await schedulePage(pageId, {
        publish_at: null,
        unpublish_at: null,
      });
      setPublishAt(updated.publish_at);
      setUnpublishAt(updated.unpublish_at);
      setMessage('Schedule cleared.');
    } catch (e) {
      setScheduleError(e instanceof Error ? e.message : 'Could not clear schedule');
    } finally {
      setBusy(false);
    }
  };

  const handleCompare = async (beforeId: number, afterId: number) => {
    if (pageId === null) return;
    if (activeDiff?.after_id === afterId && activeDiff?.before_id === beforeId) {
      setActiveDiff(null);
      return;
    }
    setDiffError(null);
    try {
      const diff = await diffRevisions(pageId, beforeId, afterId);
      setActiveDiff(diff);
    } catch (e) {
      setDiffError(e instanceof Error ? e.message : 'Could not load diff');
    }
  };

  const handleRestore = async (revisionId: number) => {
    if (pageId === null) return;
    if (!confirm('Replace the current draft with this revision?')) return;
    setBusy(true);
    setMessage(null);
    try {
      const restored = await restoreRevision(pageId, revisionId);
      const restoredData = restored.draft_data as unknown as Data;
      const restoredCanonical = restored.canonical_url ?? '';
      const restoredIndex = restored.index_in_search ?? true;
      const restoredJsonLd = restored.json_ld ? JSON.stringify(restored.json_ld, null, 2) : '';
      setTitle(restored.title);
      setMetaDescription(restored.meta_description ?? '');
      setOgImage(restored.og_image ?? '');
      setCanonicalUrl(restoredCanonical);
      setIndexInSearch(restoredIndex);
      setJsonLdText(restoredJsonLd);
      setJsonLdError(null);
      setData(restoredData);
      markSaved({
        title: restored.title,
        slug: restored.slug,
        metaDescription: restored.meta_description ?? '',
        ogImage: restored.og_image ?? '',
        canonicalUrl: restoredCanonical,
        indexInSearch: restoredIndex,
        jsonLdText: restoredJsonLd,
        data: restoredData,
      });
      setMessage('Revision restored to draft.');
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Restore failed');
    } finally {
      setBusy(false);
    }
  };

  // Debounced autosave. If the user keeps editing while a save is in
  // flight, ``saveState`` flips back to ``'idle'`` in the finally block,
  // which re-runs this effect; ``isDirty`` is still true relative to the
  // just-stored snapshot, so a fresh debounce window arms automatically
  // — the trailing edit isn't lost.
  const autosaveInFlight = useRef(false);
  useEffect(() => {
    if (pageId === null) return;
    if (!isDirty) return;
    if (busy) return;
    if (autosaveInFlight.current) return;
    const handle = window.setTimeout(async () => {
      autosaveInFlight.current = true;
      const snapshotAtSave = currentSnapshot;
      const payload = {
        ...writePayload(),
        draft_data: data as unknown as Record<string, unknown>,
      };
      setSaveState('saving');
      try {
        await savePage(pageId, payload);
        setSavedSnapshot(snapshotAtSave);
        setLastSavedAt(new Date());
        setAutosaveError(null);
        setSaveState('idle');
      } catch (e) {
        setAutosaveError(e instanceof Error ? e.message : 'Save failed');
        setSaveState('error');
      } finally {
        autosaveInFlight.current = false;
      }
    }, AUTOSAVE_DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [pageId, isDirty, busy, currentSnapshot, saveState]);

  // beforeunload: only attached while dirty, so the browser confirm
  // doesn't fire on a clean exit.
  useEffect(() => {
    if (!isDirty) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      // Required by the spec; most browsers ignore the actual string.
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [isDirty]);

  return (
    <div className="h-screen flex flex-col">
      <div className="border-b bg-white px-4 py-2 flex items-center gap-3 flex-wrap">
        <button
          type="button"
          onClick={() => router.visit('/pagebuilder')}
          className="text-gray-600 hover:underline text-sm"
        >
          ← All pages
        </button>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Page title"
          className="border rounded px-2 py-1 text-sm font-medium min-w-[16rem]"
        />
        <input
          type="text"
          value={effectiveSlug}
          onChange={(e) => {
            setSlug(slugify(e.target.value));
            setSlugTouched(true);
          }}
          placeholder="slug"
          className="border rounded px-2 py-1 text-sm font-mono min-w-[12rem]"
        />
        <StatusBadge status={status} />
        <ScheduledBadge status={status} publishAt={publishAt} unpublishAt={unpublishAt} />
        {pageId !== null && (
          <span
            className={
              saveState === 'error'
                ? 'text-xs text-red-600'
                : isDirty
                  ? 'text-xs text-amber-700'
                  : 'text-xs text-gray-500'
            }
            data-testid="autosave-status"
            title={autosaveError ?? undefined}
          >
            {formatSaveLabel(saveState, isDirty, lastSavedAt, autosaveError)}
          </span>
        )}
        <div className="ml-auto flex gap-2">
          <button
            type="button"
            onClick={() => setShowSettings((v) => !v)}
            className="px-3 py-1 text-sm rounded border hover:bg-gray-50"
          >
            SEO
          </button>
          <button
            type="button"
            onClick={() => setShowHistory((v) => !v)}
            disabled={pageId === null}
            className="px-3 py-1 text-sm rounded border hover:bg-gray-50 disabled:opacity-50"
          >
            History ({revisions.length})
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => handleSave(data)}
            className="px-3 py-1 text-sm rounded border hover:bg-gray-50 disabled:opacity-50"
          >
            Save draft
          </button>
          {status === 'published' && (
            <button
              type="button"
              disabled={busy}
              onClick={handleUnpublish}
              className="px-3 py-1 text-sm rounded border hover:bg-gray-50 disabled:opacity-50"
            >
              Unpublish
            </button>
          )}
          {status === 'draft' && (
            <button
              type="button"
              disabled={busy || pageId === null}
              onClick={handleSubmitForReview}
              className="px-3 py-1 text-sm rounded border border-amber-500 text-amber-700 hover:bg-amber-50 disabled:opacity-50"
            >
              Submit for review
            </button>
          )}
          {status === 'submitted_for_review' && (
            <>
              <button
                type="button"
                disabled={busy}
                onClick={handleReject}
                className="px-3 py-1 text-sm rounded border border-red-500 text-red-700 hover:bg-red-50 disabled:opacity-50"
              >
                Reject
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={handleApprove}
                className="px-3 py-1 text-sm rounded bg-green-600 hover:bg-green-700 text-white disabled:opacity-50"
              >
                Approve
              </button>
            </>
          )}
          <button
            type="button"
            disabled={busy}
            onClick={handlePublish}
            className="px-3 py-1 text-sm rounded bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50"
          >
            Publish
          </button>
          {status === 'published' && pageId !== null && (
            <a
              href={`/p/${effectiveSlug}`}
              target="_blank"
              rel="noopener noreferrer"
              className="px-3 py-1 text-sm rounded border hover:bg-gray-50"
            >
              View
            </a>
          )}
        </div>
        {message && <span className="w-full text-sm text-gray-600 mt-1">{message}</span>}
      </div>

      {rejectionNote && status === 'draft' && (
        <div className="border-b bg-red-50 px-4 py-3 text-sm text-red-800">
          <strong>Rejected:</strong> {rejectionNote}
        </div>
      )}

      {showSettings && (
        <div className="border-b bg-gray-50 px-4 py-3 grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
          <label className="flex flex-col gap-1">
            <span className="font-medium text-gray-700">Meta description</span>
            <textarea
              value={metaDescription}
              onChange={(e) => setMetaDescription(e.target.value)}
              maxLength={500}
              rows={2}
              placeholder="Shown in search results and link previews."
              className="border rounded px-2 py-1"
            />
            <span className="text-xs text-gray-500">{metaDescription.length}/500</span>
          </label>
          <label className="flex flex-col gap-1">
            <span className="font-medium text-gray-700">Open Graph image URL</span>
            <input
              type="text"
              value={ogImage}
              onChange={(e) => setOgImage(e.target.value)}
              maxLength={500}
              placeholder="https://… or /media/pagebuilder/…"
              className="border rounded px-2 py-1 font-mono"
            />
            <span className="text-xs text-gray-500">
              Paste a URL from the{' '}
              <a href="/pagebuilder/media" className="text-blue-600 hover:underline">
                media library
              </a>
              .
            </span>
          </label>
          <label className="flex flex-col gap-1">
            <span className="font-medium text-gray-700">Canonical URL</span>
            <input
              type="text"
              value={canonicalUrl}
              onChange={(e) => setCanonicalUrl(e.target.value)}
              maxLength={500}
              placeholder="Defaults to this page's own URL."
              className="border rounded px-2 py-1 font-mono"
            />
            <span className="text-xs text-gray-500">
              Override when this page is a duplicate of content hosted elsewhere.
            </span>
          </label>
          <label className="flex items-start gap-2 mt-1">
            <input
              type="checkbox"
              checked={indexInSearch}
              onChange={(e) => setIndexInSearch(e.target.checked)}
              className="mt-1"
            />
            <span className="flex flex-col">
              <span className="font-medium text-gray-700">
                Allow search engines to index this page
              </span>
              <span className="text-xs text-gray-500">
                Uncheck to emit <code>noindex,nofollow</code> and exclude from sitemap.
              </span>
            </span>
          </label>
          <label className="flex flex-col gap-1 md:col-span-2">
            <span className="font-medium text-gray-700">JSON-LD structured data</span>
            <textarea
              value={jsonLdText}
              onChange={(e) => {
                setJsonLdText(e.target.value);
                const trimmed = e.target.value.trim();
                if (!trimmed) {
                  setJsonLdError(null);
                  return;
                }
                try {
                  const parsed = JSON.parse(trimmed);
                  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
                    setJsonLdError('JSON-LD must be a JSON object.');
                  } else {
                    setJsonLdError(null);
                  }
                } catch (err) {
                  setJsonLdError(err instanceof Error ? err.message : 'Invalid JSON.');
                }
              }}
              rows={6}
              placeholder='{"@context":"https://schema.org","@type":"Article",…}'
              className="border rounded px-2 py-1 font-mono text-xs"
            />
            {jsonLdError ? (
              <span className="text-xs text-red-600" data-testid="json-ld-error">
                {jsonLdError}
              </span>
            ) : (
              <span className="text-xs text-gray-500">
                Embedded inside <code>&lt;script type="application/ld+json"&gt;</code>. Leave blank
                to omit.
              </span>
            )}
          </label>

          <fieldset className="md:col-span-2 border rounded p-3 bg-white">
            <legend className="px-1 text-sm font-medium text-gray-700">Schedule</legend>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <label className="flex flex-col gap-1">
                <span className="text-xs text-gray-700">Publish at</span>
                <input
                  type="datetime-local"
                  value={toLocalInput(publishAt)}
                  onChange={(e) => setPublishAt(fromLocalInput(e.target.value))}
                  className="border rounded px-2 py-1"
                  data-testid="schedule-publish-at"
                />
                <span className="text-xs text-gray-500">
                  Draft auto-publishes at this time. Cleared after the flip.
                </span>
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-gray-700">Unpublish at</span>
                <input
                  type="datetime-local"
                  value={toLocalInput(unpublishAt)}
                  onChange={(e) => setUnpublishAt(fromLocalInput(e.target.value))}
                  className="border rounded px-2 py-1"
                  data-testid="schedule-unpublish-at"
                />
                <span className="text-xs text-gray-500">
                  Published page reverts to draft at this time.
                </span>
              </label>
            </div>
            <div className="mt-2 flex items-center gap-2">
              <button
                type="button"
                onClick={handleSaveSchedule}
                disabled={busy || pageId === null}
                className="px-3 py-1 text-sm rounded border hover:bg-gray-50 disabled:opacity-50"
                data-testid="schedule-save"
              >
                Save schedule
              </button>
              <button
                type="button"
                onClick={handleClearSchedule}
                disabled={busy || pageId === null || (publishAt === null && unpublishAt === null)}
                className="px-3 py-1 text-sm rounded border hover:bg-gray-50 disabled:opacity-50"
              >
                Clear
              </button>
              {scheduleError && (
                <span className="text-xs text-red-600" data-testid="schedule-error">
                  {scheduleError}
                </span>
              )}
            </div>
          </fieldset>
        </div>
      )}

      {showHistory && (
        <div className="border-b bg-gray-50 px-4 py-3 text-sm">
          {revisions.length === 0 ? (
            <p className="text-gray-500">No history yet. Publish or submit to record one.</p>
          ) : (
            <ul className="space-y-1 max-h-48 overflow-y-auto">
              {revisions.map((r, idx) => {
                // Revisions are sorted newest-first, so the "previous" is
                // the next index. The last item has no predecessor.
                const previous = revisions[idx + 1];
                const isOpen =
                  activeDiff !== null &&
                  activeDiff.after_id === r.id &&
                  previous !== undefined &&
                  activeDiff.before_id === previous.id;
                return (
                  <li key={r.id} className="flex items-start justify-between gap-3 py-1">
                    <div className="flex-1 min-w-0">
                      <span className="font-medium">{EVENT_LABELS[r.event] ?? r.event}</span>
                      <span className="text-gray-700 ml-2">{r.title}</span>
                      <span className="text-gray-500 ml-2">
                        {new Date(r.created_at).toLocaleString()}
                      </span>
                      {r.created_by && (
                        <span className="text-gray-500 ml-2">by {r.created_by}</span>
                      )}
                      {r.note && (
                        <div className="text-gray-800 mt-0.5 break-words">Note: {r.note}</div>
                      )}
                    </div>
                    <div className="flex gap-3 shrink-0">
                      {previous && (
                        <button
                          type="button"
                          onClick={() => handleCompare(previous.id, r.id)}
                          className="text-blue-600 hover:underline"
                          data-testid={`compare-${r.id}`}
                        >
                          {isOpen ? 'Hide diff' : 'Compare'}
                        </button>
                      )}
                      {RESTORABLE_EVENTS.has(r.event) && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => handleRestore(r.id)}
                          className="text-blue-600 hover:underline disabled:opacity-50"
                        >
                          Restore as draft
                        </button>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
          {diffError && (
            <p className="mt-2 text-xs text-red-600" data-testid="diff-error">
              {diffError}
            </p>
          )}
          {activeDiff && <DiffSummary diff={activeDiff} />}
        </div>
      )}

      <div className="flex-1 min-h-0">
        <Puck
          config={puckConfig}
          data={data}
          viewports={editorViewports}
          iframe={{ enabled: true }}
          onChange={setData}
          onPublish={(newData) => {
            setData(newData);
            void handleSave(newData);
          }}
        />
      </div>
    </div>
  );
}
