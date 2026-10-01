import { router } from '@inertiajs/react';
import { useState } from 'react';
import { toast } from 'sonner';

import { buildChanges, extraCreateFields, stripUids } from '../components/typeeditor/formHelpers';
import type { EditableField, TypeMetadataValues } from '../components/typeeditor/types';
import { ApiError, createType } from '../utils/api';
import type { Translate } from '../utils/translate';
import type { TypeRead, ValidationError } from '../utils/types';
import type { SchemaApplyBody, useSchemaApply } from './useSchemaApply';
import type { useUnsavedGuard } from './useUnsavedGuard';

/**
 * `TypeEditor`'s Save button: create-a-type or update-the-schema, split out
 * of the page component for the 300-line cap. Everything about *how* the
 * save is dispatched — new type vs. an existing one's changes, the 409 that
 * is really about `translatable`, a 422 the create endpoint answers with —
 * lives here; `TypeEditor` still owns `attemptUpdate` (it closes over
 * `current` the same way the caller's other handlers do) and reverting the
 * `translatable` switch on a refusal, both passed in.
 */
export function useTypeEditorSave({
  isNew,
  current,
  values,
  fields,
  guard,
  schemaApply,
  attemptUpdate,
  onTranslatableRevert,
  t,
}: {
  isNew: boolean;
  current: TypeRead | null;
  values: TypeMetadataValues;
  fields: EditableField[];
  guard: ReturnType<typeof useUnsavedGuard>;
  schemaApply: ReturnType<typeof useSchemaApply>;
  attemptUpdate: (body: SchemaApplyBody) => Promise<TypeRead>;
  /** Reverts the on-screen `translatable` switch to the server's own value
   *  after a 409 refuses turning it off (UX-7) — the switch already moved
   *  on click, and the error under it must not disagree with what's shown. */
  onTranslatableRevert: () => void;
  t: Translate;
}) {
  const [pending, setPending] = useState(false);
  const [createErrors, setCreateErrors] = useState<ValidationError[]>([]);
  // A 409 from turning "Translatable" off while foreign-locale records exist
  // (§4.1) — none of `useSchemaApply`'s shapes, so it lands here.
  const [translatableError, setTranslatableError] = useState<string | null>(null);

  const save = async () => {
    setPending(true);
    setTranslatableError(null);
    let changedTranslatable = false;
    try {
      if (isNew) {
        setCreateErrors([]);
        const created = await createType({
          key: values.key,
          label: values.label,
          label_plural: values.labelPlural,
          fields: stripUids(fields),
          ...extraCreateFields(values),
        });
        // Written; the guard must not ask about it on the way out.
        guard.allow();
        // U9: this landed on the saved editor with no confirmation at all —
        // the same pattern the record editor already got right (R22a).
        toast.success(t('records.type_editor.created', { defaultValue: 'Type created' }));
        router.visit(`/admin/records/types/${created.key}`);
        return;
      }
      if (!current) return;
      const changes = buildChanges(current, values, fields);
      changedTranslatable = 'translatable' in changes;
      if (Object.keys(changes).length === 0) {
        // Unreachable while Save is disabled on a clean draft (R22b), kept
        // as the honest answer rather than a green "Saved" for a no-op.
        toast(t('records.type_editor.no_changes', { defaultValue: 'No changes to save' }));
        return;
      }
      schemaApply.reset();
      await schemaApply.run(attemptUpdate, { expected_version: current.version, ...changes });
    } catch (err) {
      // Turning "Translatable" off while records in another locale exist —
      // a 409 that carries none of `useSchemaApply`'s four known shapes
      // (`current`/`report`/`conflicts`), so it lands here instead of there.
      if (err instanceof ApiError && err.status === 409 && changedTranslatable) {
        setTranslatableError(err.body?.detail ?? err.message);
        onTranslatableRevert();
      } else if (err instanceof ApiError && err.status === 422 && err.body?.errors) {
        setCreateErrors(err.body.errors);
      } else {
        toast.error(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setPending(false);
    }
  };

  return { pending, createErrors, translatableError, setTranslatableError, save };
}
