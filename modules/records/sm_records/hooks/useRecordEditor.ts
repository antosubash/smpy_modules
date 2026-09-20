import { router } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { useState } from 'react';
import { toast } from 'sonner';

import { ApiError } from '../utils/api';
import { createRecord, updateRecord } from '../utils/api-records';
import type { RecordRead, RecordStatus, TypeRead } from '../utils/types';
import { useRecordForm } from './useRecordForm';

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

  /** `overwriteVersion` is set only when this save follows "Overwrite
   *  anyway" on the conflict panel (H1): it resends the payload the person
   *  already has, but stamped with the version the 409 told us the server
   *  is actually on — a plain re-press of Save would otherwise keep sending
   *  the stale `current.version` and 409 forever. */
  const save = async (overwriteVersion?: number) => {
    setConflict(null);
    const data = form.validateAndBuild();
    if (data === null) return;

    const payload = {
      data,
      status,
      slug: slug || null,
      position: Number(position) || 0,
      ...(opts.showLocalePicker ? { locale } : {}),
    };
    setPending(true);
    try {
      const expectedVersion = overwriteVersion ?? current?.version ?? 0;
      const saved = isNew
        ? await createRecord(type.key, payload)
        : await updateRecord(type.key, current?.uuid ?? '', expectedVersion, payload);
      if (isNew) {
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
      } else {
        toast.error(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setPending(false);
    }
  };

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
