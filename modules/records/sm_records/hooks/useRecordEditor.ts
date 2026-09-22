import { router } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import { ApiError } from '../utils/api';
import { createRecord, updateRecord } from '../utils/api-records';
import { conflictField, humanizeCollisionDetail } from '../utils/conflicts';
import { firstErrorInDomOrder, focusInvalidInput } from '../utils/focus-invalid';
import type { RecordRead, RecordStatus, TypeRead } from '../utils/types';
import { parsePosition } from '../utils/values';
import { useRecordForm } from './useRecordForm';
import { useUnsavedGuard } from './useUnsavedGuard';

/** Where a create leaves word that it happened, for the editor it navigates
 *  to (R22a).
 *
 * `sessionStorage` and not a query parameter or component state: the create
 * *navigates*, so nothing this hook holds survives it — and a `?created=1`
 * would sit in the address bar of a URL people copy and share, claiming the
 * record was created again every time it is opened. Read once and cleared,
 * so a reload doesn't repeat the toast either. */
const CREATED_FLAG = 'sm-records-created-uuid';

/** Remember it now; the page this navigates to is the one that will say so.
 *  A browser with storage blocked simply doesn't get the toast. */
function rememberCreated(uuid: string): void {
  try {
    window.sessionStorage.setItem(CREATED_FLAG, uuid);
  } catch {
    // Private mode, blocked site data — nothing to recover, and a missing
    // confirmation must never fail a save that already succeeded.
  }
}

/** …and take it, if it is this record's. */
function takeCreated(uuid: string | undefined): boolean {
  if (typeof window === 'undefined' || uuid === undefined) return false;
  try {
    if (window.sessionStorage.getItem(CREATED_FLAG) !== uuid) return false;
    window.sessionStorage.removeItem(CREATED_FLAG);
    return true;
  } catch {
    return false;
  }
}

/**
 * `RecordEditor`'s own state and save/conflict/restore handlers, split out
 * of the page component for the 300-line cap — the render stays in
 * `pages/RecordEditor.tsx`, everything about *what happens* on Save,
 * "Reload" and "Overwrite anyway" (H1), and a trash/revision restore lives
 * here.
 */
export function useRecordEditor(
  type: TypeRead,
  record: RecordRead | null,
  opts: {
    /** Only a new record on a translatable type with several locales sends
     *  `locale` in the create payload — an existing record's language is
     *  fixed for its lifetime. */
    showLocalePicker: boolean;
    defaultLocale: string;
  },
) {
  const { t } = useT();
  const isNew = record === null;
  const [current, setCurrent] = useState<RecordRead | null>(record);
  const [status, setStatus] = useState<RecordStatus>(record?.status ?? 'draft');
  const [slug, setSlug] = useState(record?.slug ?? '');
  const [position, setPosition] = useState(String(record?.position ?? 0));
  const [locale, setLocale] = useState(opts.defaultLocale);
  const [conflict, setConflict] = useState<RecordRead | null>(null);
  const [pending, setPending] = useState(false);
  const form = useRecordForm(type, record);

  /** Unsaved work is the form's values *and* the envelope inputs around it —
   *  a status flipped to Published and nothing else is still an edit worth
   *  warning about (R12c). Measured against `current`, not the page's own
   *  `record` prop, so a successful save makes the page clean again without
   *  a reload. */
  const dirty =
    form.dirty ||
    status !== (current?.status ?? 'draft') ||
    slug !== (current?.slug ?? '') ||
    position !== String(current?.position ?? 0);
  const { allow } = useUnsavedGuard(dirty);

  // "Record created", on arrival at the editor the create navigated to
  // (R22a). The toast cannot fire before the visit: this page is the one
  // that mounts the `<Toaster>`, and the old page's is gone by then.
  useEffect(() => {
    if (takeCreated(record?.uuid)) {
      toast.success(t('records.editor.created', { defaultValue: 'Record created' }));
    }
  }, [record?.uuid, t]);

  /**
   * A 409 that is a collision, not a stale read (UX review R8b).
   *
   * A duplicate `unique` value or a taken slug used to be a red toast
   * carrying the server's sentence and nothing else — no mark on the input
   * that caused it, and no hint that the record holding the value might be
   * sitting in the Trash, where a trashed record keeps its claims until it is
   * purged. Both halves matter: the mark says *where*, the sentence says
   * *why nothing on screen shows the conflict*.
   *
   * Announced once, not twice (UX review rough edge): when a field owns the
   * collision, the inline error under that input *is* the announcement — a
   * toast saying the same thing a beat later is the double-up the imports
   * flow (R26) was fixed to stop doing. The toast is for the one case an
   * inline error can't cover: a collision `conflictField` couldn't attribute
   * to any of this type's fields.
   */
  const markCollision = (err: ApiError) => {
    const detail = typeof err.body?.detail === 'string' ? err.body.detail : err.message;
    const inTrash = t('records.editor.unique_in_trash', {
      defaultValue:
        'A record with this value already exists — it may be in the Trash. Open the Trash and either restore it and change its value, or delete it permanently to release the value.',
    });
    const field = conflictField(
      detail,
      type.fields.map((one) => one.key),
    );
    if (field === null) {
      toast.error(detail);
      return;
    }
    // U15: the server's own sentence names the field/type by wire key
    // ('ticket_code', 'qa_ux_event') — an operator who only ever sees
    // labels reads that as implementation detail leaking through.
    const fieldLabel = type.fields.find((one) => one.key === field)?.label ?? null;
    const humanDetail = humanizeCollisionDetail(detail, fieldLabel, type.label);
    // The slug field is the one collision an operator often never typed
    // into — it derives from Title by default — so naming *that* recovery
    // is what the generic "already taken" sentence is missing (U5).
    const extra =
      field === 'slug'
        ? t('records.editor.slug_collision_help', {
            defaultValue: ' Change the Title, or set a distinct Slug under Advanced.',
          })
        : '';
    form.setServerErrors([{ field, message: `${humanDetail} ${inTrash}${extra}` }]);
    focusInvalidInput(field);
  };

  /** `overwriteVersion` is set only when this save follows "Overwrite
   *  anyway" on the conflict panel (H1): it resends the payload the person
   *  already has, but stamped with the version the 409 told us the server
   *  is actually on — a plain re-press of Save would otherwise keep sending
   *  the stale `current.version` and 409 forever. */
  const save = async (overwriteVersion?: number) => {
    setConflict(null);
    const data = form.validateAndBuild();
    // Every schema field gets a client-side check; the envelope's one
    // numeric input used to get none (R14). Checked after the field
    // validator so its own `setServerErrors([])` cannot wipe this message.
    const positionValue = parsePosition(position);
    if (positionValue === null) {
      form.setServerErrors([
        {
          field: 'position',
          message: t('records.validation.position', {
            defaultValue: 'Must be a whole number — use 0 for no particular order.',
          }),
        },
      ]);
    }
    if (data === null || positionValue === null) {
      // The refusal is already on screen — under an input that may be a
      // screen or more above the button just pressed. Go there (R6).
      const first = data === null ? form.firstInvalidKey() : 'position';
      if (first) focusInvalidInput(first);
      return;
    }

    const payload = {
      data,
      status,
      slug: slug || null,
      position: positionValue,
      ...(opts.showLocalePicker ? { locale } : {}),
    };
    setPending(true);
    try {
      const expectedVersion = overwriteVersion ?? current?.version ?? 0;
      const saved = isNew
        ? await createRecord(type.key, payload)
        : await updateRecord(type.key, current?.uuid ?? '', expectedVersion, payload);
      if (isNew) {
        // The work is written; the guard must not ask about it on the way
        // out (R12c). `allow` is a ref, so this takes effect immediately.
        allow();
        rememberCreated(saved.uuid);
        router.visit(`/admin/records/${type.key}/${saved.uuid}`);
        return;
      }
      setCurrent(saved);
      // The server can derive its own `slug` (and, in principle, adjust
      // `status`/`position`), so the envelope inputs have to re-sync from
      // what it actually stored — otherwise a server-derived slug doesn't
      // show until the next full reload.
      setStatus(saved.status);
      setSlug(saved.slug ?? '');
      setPosition(String(saved.position));
      form.reset(saved);
      toast.success(t('records.editor.saved', { defaultValue: 'Saved' }));
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.body?.current) {
        setConflict(err.body.current as RecordRead);
      } else if (err instanceof ApiError && err.status === 422 && err.body?.errors) {
        form.setServerErrors(err.body.errors);
        // In render order, not in the server's enumeration order (R17) —
        // the same rule `useRecordForm` applies to the client validator's
        // errors, so the two paths agree about where a refused save lands.
        const first = firstErrorInDomOrder(
          err.body.errors,
          type.fields.map((field) => field.key),
        );
        if (first) focusInvalidInput(first);
      } else if (err instanceof ApiError && err.status === 409) {
        markCollision(err);
      } else {
        toast.error(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setPending(false);
    }
  };

  // ⌘S / Ctrl+S (R13, missing-UI M9). Read through refs so the listener is
  // installed once and still calls the current `save` — and so a second
  // press while one is in flight is ignored rather than queued behind it.
  const saveRef = useRef(save);
  saveRef.current = save;
  const pendingRef = useRef(pending);
  pendingRef.current = pending;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 's' || event.altKey) return;
      if (!(event.metaKey || event.ctrlKey)) return;
      // The browser's own "save this page" is never what someone means with
      // an editor open.
      event.preventDefault();
      if (pendingRef.current) return;
      void saveRef.current();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const reloadFromConflict = (server: RecordRead) => {
    setCurrent(server);
    setStatus(server.status);
    setSlug(server.slug ?? '');
    setPosition(String(server.position));
    form.reset(server);
    setConflict(null);
  };

  /** A trash-restore (`RecordActions`) and a revision restore (`RecordRevisions`)
   *  both hand back a fresh `RecordRead`, so the envelope inputs and form re-sync. */
  const applyRestored = (restored: RecordRead) => {
    setCurrent(restored);
    setStatus(restored.status);
    setSlug(restored.slug ?? '');
    setPosition(String(restored.position));
    form.reset(restored);
  };

  return {
    isNew,
    current,
    dirty,
    /** Lets the page navigate away on purpose (the header's "Cancel" is the
     *  one place that asks first, via the guard itself) without the guard
     *  double-asking about work it already knows about. */
    allowNavigation: allow,
    status,
    slug,
    position,
    locale,
    conflict,
    pending,
    form,
    setStatus,
    setSlug,
    setPosition,
    setLocale,
    save,
    reloadFromConflict,
    applyRestored,
  };
}
