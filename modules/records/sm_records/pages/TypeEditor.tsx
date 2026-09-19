import { Head, router } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@simple-module-py/ui/components/ui/card';
import { AdminLayout } from '@simple-module-py/ui/layouts/AdminLayout';
import type React from 'react';
import { useState } from 'react';
import { toast } from 'sonner';

import { DeleteTypeSection } from '../components/typeeditor/DeleteTypeSection';
import { FieldList } from '../components/typeeditor/FieldList';
import { TypeConflictNotice } from '../components/typeeditor/TypeConflictNotice';
import { TypeMetadataForm } from '../components/typeeditor/TypeMetadataForm';
import {
  type EditableField,
  TOP_LEVEL_ERROR_FIELDS,
  type TypeEditorProps,
  type TypeMetadataValues,
} from '../components/typeeditor/types';
import { ApiError, type CreateTypePayload, createType, updateType } from '../utils/api';
import type { TypeRead, ValidationError } from '../utils/types';

const TYPES_LIST_HREF = '/admin/records/';

function metadataFrom(type: TypeRead | null): TypeMetadataValues {
  return {
    key: type?.key ?? '',
    label: type?.label ?? '',
    labelPlural: type?.label_plural ?? '',
    description: type?.description ?? '',
    icon: type?.icon ?? '',
    isPublic: type?.is_public ?? false,
    allowedRoles: type?.allowed_roles ?? [],
    displayField: type?.display_field ?? '',
    slugField: type?.slug_field ?? '',
  };
}

function sameStringSet(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  const sa = [...a].sort();
  const sb = [...b].sort();
  return sa.every((v, i) => v === sb[i]);
}

/** The optional metadata the editor collects for a new type, in the shape
 *  `createType` sends. Absent keys are left to the server's defaults. */
function extraCreateFields(values: TypeMetadataValues): Partial<CreateTypePayload> {
  const extra: Partial<CreateTypePayload> = {};
  if (values.description) extra.description = values.description;
  if (values.icon) extra.icon = values.icon;
  if (values.isPublic) extra.is_public = true;
  if (values.allowedRoles.length > 0) extra.allowed_roles = values.allowedRoles;
  if (values.displayField) extra.display_field = values.displayField;
  if (values.slugField) extra.slug_field = values.slugField;
  return extra;
}

/** Only what changed, top-level, against `current` — `updateType` sends
 *  exactly these as `PUT`'s body alongside `expected_version` (design's
 *  contract: send only changed top-level keys). */
function buildChanges(
  current: TypeRead,
  values: TypeMetadataValues,
  fields: EditableField[],
): Record<string, unknown> {
  const changes: Record<string, unknown> = {};
  if (values.label !== current.label) changes.label = values.label;
  if (values.labelPlural !== current.label_plural) changes.label_plural = values.labelPlural;
  if (values.description !== (current.description ?? '')) {
    changes.description = values.description || null;
  }
  if (values.icon !== (current.icon ?? '')) changes.icon = values.icon || null;
  if (values.isPublic !== current.is_public) changes.is_public = values.isPublic;
  if (!sameStringSet(values.allowedRoles, current.allowed_roles)) {
    changes.allowed_roles = values.allowedRoles;
  }
  if (values.displayField !== (current.display_field ?? '')) {
    changes.display_field = values.displayField || null;
  }
  if (values.slugField !== (current.slug_field ?? '')) {
    changes.slug_field = values.slugField || null;
  }
  if (JSON.stringify(fields) !== JSON.stringify(current.fields)) {
    changes.fields = fields;
  }
  return changes;
}

/** `Records/TypeEditor` — `/admin/records/types/new` and `/…/types/{key}`.
 *
 * The schema editor from design §6.1/§7.2/§16: type metadata, the field
 * list (with `indexed` — "the single most consequential choice on the
 * screen", §7.2 — front and center), and, on an existing type, the danger
 * zone. A populated type's `fields`/`display_field`/`slug_field` are
 * read-only (`fields_locked`); everything else stays editable. */
function TypeEditor({ type, target_types, roles }: TypeEditorProps) {
  const { t } = useT();
  const isNew = type === null;
  const [current, setCurrent] = useState<TypeRead | null>(type);
  const [values, setValues] = useState<TypeMetadataValues>(metadataFrom(type));
  const [fields, setFields] = useState<EditableField[]>(type?.fields ?? []);
  const [originalKeys] = useState<Set<string>>(new Set((type?.fields ?? []).map((f) => f.key)));
  const [errors, setErrors] = useState<ValidationError[]>([]);
  const [conflict, setConflict] = useState<TypeRead | null>(null);
  const [lockedNotice, setLockedNotice] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const fieldsLocked = current?.fields_locked ?? false;
  const topLevelErrors = errors.filter((e) => TOP_LEVEL_ERROR_FIELDS.has(e.field));
  const fieldErrors = errors.filter((e) => !TOP_LEVEL_ERROR_FIELDS.has(e.field));

  const applySaved = (saved: TypeRead) => {
    setCurrent(saved);
    setValues(metadataFrom(saved));
    setFields(saved.fields);
  };

  const save = async () => {
    setErrors([]);
    setConflict(null);
    setLockedNotice(null);
    setPending(true);
    try {
      if (isNew) {
        const created = await createType({
          key: values.key,
          label: values.label,
          label_plural: values.labelPlural,
          fields,
          ...extraCreateFields(values),
        });
        router.visit(`/admin/records/types/${created.key}`);
        return;
      }
      if (!current) return;
      const changes = buildChanges(current, values, fields);
      if (Object.keys(changes).length === 0) {
        toast.success(t('records.editor.saved', { defaultValue: 'Saved' }));
        return;
      }
      const updated = await updateType(current.key, current.version, changes);
      applySaved(updated);
      toast.success(t('records.editor.saved', { defaultValue: 'Saved' }));
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.body?.current) {
        setConflict(err.body.current as TypeRead);
      } else if (err instanceof ApiError && err.status === 409) {
        setLockedNotice(err.body?.detail ?? err.message);
      } else if (err instanceof ApiError && err.status === 422 && err.body?.errors) {
        setErrors(err.body.errors);
      } else {
        toast.error(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setPending(false);
    }
  };

  const reloadFromConflict = (server: TypeRead) => {
    applySaved(server);
    setConflict(null);
  };

  return (
    <>
      <Head
        title={
          isNew
            ? t('records.type_editor.title_new', { defaultValue: 'New type' })
            : t('records.type_editor.title_edit', {
                defaultValue: 'Edit {{label}}',
                label: current?.label ?? '',
              })
        }
      />
      <PageShell
        title={
          isNew
            ? t('records.type_editor.title_new', { defaultValue: 'New type' })
            : (current?.label ?? '')
        }
        actions={
          <Button variant="outline" onClick={() => router.visit(TYPES_LIST_HREF)}>
            {t('records.editor.cancel', { defaultValue: 'Cancel' })}
          </Button>
        }
      >
        <div className="space-y-6">
          {conflict && <TypeConflictNotice current={conflict} onReload={reloadFromConflict} />}
          {lockedNotice && (
            <p
              className="rounded-md border border-destructive/50 p-3 text-sm text-destructive"
              role="alert"
            >
              {lockedNotice}
            </p>
          )}

          <Card>
            <CardHeader>
              <CardTitle>
                {t('records.type_editor.section_details', { defaultValue: 'Details' })}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <TypeMetadataForm
                isNew={isNew}
                fieldsLocked={fieldsLocked}
                fields={fields}
                roles={roles}
                values={values}
                onChange={(patch) => setValues((prev) => ({ ...prev, ...patch }))}
                errors={topLevelErrors}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>
                {t('records.type_editor.section_fields', { defaultValue: 'Fields' })}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <FieldList
                fields={fields}
                originalKeys={originalKeys}
                targetTypes={target_types}
                locked={fieldsLocked}
                recordCount={current?.record_count ?? 0}
                trashedRecordCount={current?.trashed_record_count ?? 0}
                errors={fieldErrors}
                onChange={setFields}
              />
            </CardContent>
          </Card>

          <div>
            <Button type="button" disabled={pending} onClick={() => void save()}>
              {pending
                ? t('records.editor.saving', { defaultValue: 'Saving…' })
                : t('records.editor.save', { defaultValue: 'Save' })}
            </Button>
          </div>

          {!isNew && current && (
            <DeleteTypeSection type={current} onDeleted={() => router.visit(TYPES_LIST_HREF)} />
          )}
        </div>
      </PageShell>
    </>
  );
}

TypeEditor.layout = (page: React.ReactNode) => <AdminLayout>{page}</AdminLayout>;
export default TypeEditor;
