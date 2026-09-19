import { Head, router } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@simple-module-py/ui/components/ui/card';
import { AdminLayout } from '@simple-module-py/ui/layouts/AdminLayout';
import type React from 'react';
import { useCallback, useState } from 'react';
import { toast } from 'sonner';

import { DeleteTypeSection } from '../components/typeeditor/DeleteTypeSection';
import { FieldList } from '../components/typeeditor/FieldList';
import {
  buildChanges,
  extraCreateFields,
  metadataFrom,
  schemaIsDirty,
} from '../components/typeeditor/formHelpers';
import { ReindexStatus } from '../components/typeeditor/ReindexStatus';
import { SchemaConflictPanel } from '../components/typeeditor/SchemaConflictPanel';
import { SchemaPreviewPanel } from '../components/typeeditor/SchemaPreviewPanel';
import { TypeConflictNotice } from '../components/typeeditor/TypeConflictNotice';
import { TypeMetadataForm } from '../components/typeeditor/TypeMetadataForm';
import { TypeRevisions } from '../components/typeeditor/TypeRevisions';
import {
  type EditableField,
  TOP_LEVEL_ERROR_FIELDS,
  type TypeEditorProps,
} from '../components/typeeditor/types';
import type { SchemaApplyBody } from '../hooks/useSchemaApply';
import { useSchemaApply } from '../hooks/useSchemaApply';
import { ApiError, createType, updateType } from '../utils/api';
import type { TypeRead, ValidationError } from '../utils/types';

const TYPES_LIST_HREF = '/admin/records/';

/** `Records/TypeEditor` — `/admin/records/types/new` and `/…/types/{key}`.
 *
 * The schema editor from design §6.1/§7.2/§16: type metadata, the field
 * list (with `indexed` — "the single most consequential choice on the
 * screen", §7.2 — front and center), and, on an existing type, the danger
 * zone. Phase 3 lifts the Phase 1 lock: a populated type's `fields`,
 * `display_field` and `slug_field` are editable here too, checked by
 * "Preview changes" before saving and by the save itself, which the server
 * enforces with a dry-run (§8.2) rather than trusting the client to have run
 * one. */
function TypeEditor({ type, target_types, roles }: TypeEditorProps) {
  const { t } = useT();
  const isNew = type === null;
  const [current, setCurrent] = useState<TypeRead | null>(type);
  const [values, setValues] = useState(metadataFrom(type));
  const [fields, setFields] = useState<EditableField[]>(type?.fields ?? []);
  const [originalKeys] = useState<Set<string>>(new Set((type?.fields ?? []).map((f) => f.key)));
  const [createErrors, setCreateErrors] = useState<ValidationError[]>([]);
  const [pending, setPending] = useState(false);

  const applySaved = (saved: TypeRead) => {
    setCurrent(saved);
    setValues(metadataFrom(saved));
    setFields(saved.fields);
  };

  const schemaApply = useSchemaApply((result) => {
    applySaved(result);
    toast.success(t('records.editor.saved', { defaultValue: 'Saved' }));
  });

  const attemptUpdate = useCallback(
    (body: SchemaApplyBody) => {
      if (!current) return Promise.reject(new Error('No type loaded to update'));
      const { expected_version, ...rest } = body;
      return updateType(current.key, expected_version, rest);
    },
    [current],
  );

  const activeErrors = isNew ? createErrors : schemaApply.errors;
  const topLevelErrors = activeErrors.filter((e) => TOP_LEVEL_ERROR_FIELDS.has(e.field));
  const fieldErrors = activeErrors.filter((e) => !TOP_LEVEL_ERROR_FIELDS.has(e.field));
  const dirty = !isNew && schemaIsDirty(current, values, fields);

  const save = async () => {
    setPending(true);
    try {
      if (isNew) {
        setCreateErrors([]);
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
      schemaApply.reset();
      await schemaApply.run(attemptUpdate, { expected_version: current.version, ...changes });
    } catch (err) {
      if (err instanceof ApiError && err.status === 422 && err.body?.errors) {
        setCreateErrors(err.body.errors);
      } else {
        toast.error(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setPending(false);
    }
  };

  const reloadFromConflict = (server: TypeRead) => {
    applySaved(server);
    schemaApply.reset();
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
          {schemaApply.versionConflict && (
            <TypeConflictNotice
              current={schemaApply.versionConflict}
              onReload={reloadFromConflict}
            />
          )}

          {!isNew && current && <ReindexStatus type={current} />}

          <Card>
            <CardHeader>
              <CardTitle>
                {t('records.type_editor.section_details', { defaultValue: 'Details' })}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <TypeMetadataForm
                isNew={isNew}
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
            <CardContent className="space-y-4">
              {!isNew && current && (
                <p className="text-sm text-muted-foreground">
                  {t('records.type_editor.live_notice', {
                    count: current.record_count,
                    trashed: current.trashed_record_count,
                    defaultValue:
                      '{{count}} live, {{trashed}} trashed records — changes are checked against them before they apply.',
                  })}
                </p>
              )}
              <FieldList
                fields={fields}
                originalKeys={originalKeys}
                targetTypes={target_types}
                disabled={pending}
                errors={fieldErrors}
                onChange={setFields}
              />
              {!isNew && current && (
                <SchemaPreviewPanel typeKey={current.key} fields={fields} dirty={dirty} />
              )}
            </CardContent>
          </Card>

          <div>
            <Button type="button" disabled={pending} onClick={() => void save()}>
              {pending
                ? t('records.editor.saving', { defaultValue: 'Saving…' })
                : t('records.editor.save', { defaultValue: 'Save' })}
            </Button>
          </div>

          <SchemaConflictPanel
            report={schemaApply.report}
            conflicts={schemaApply.conflicts}
            pending={schemaApply.pending || pending}
            onForce={() => schemaApply.retryWith({ force: true })}
            onOrphaned={(choice) => schemaApply.retryWith({ orphaned: choice })}
          />

          {!isNew && current && <TypeRevisions type={current} onRestored={applySaved} />}

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
