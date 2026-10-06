import { Head, router } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@simple-module-py/ui/components/ui/card';
import { useCallback, useState } from 'react';
import { toast } from 'sonner';

import { RecordsLayout } from '../components/RecordsLayout';
import { TenantBadge } from '../components/TenantBadge';
import { DeleteTypeSection } from '../components/typeeditor/DeleteTypeSection';
import { groupErrors } from '../components/typeeditor/errors';
import { FieldsCard } from '../components/typeeditor/FieldsCard';
import {
  metadataFrom,
  schemaIsDirty,
  typeIsDirty,
  withUids,
} from '../components/typeeditor/formHelpers';
import { PointerFields } from '../components/typeeditor/PointerFields';
import { ReindexStatus } from '../components/typeeditor/ReindexStatus';
import { SaveBar } from '../components/typeeditor/SaveBar';
import { SchemaConflictPanel } from '../components/typeeditor/SchemaConflictPanel';
import { TypeConflictNotice } from '../components/typeeditor/TypeConflictNotice';
import { TypeIoMenu } from '../components/typeeditor/TypeIoMenu';
import { TypeMetadataForm } from '../components/typeeditor/TypeMetadataForm';
import { TypeRevisions } from '../components/typeeditor/TypeRevisions';
import type { EditableField, TypeEditorProps } from '../components/typeeditor/types';
import type { SchemaApplyBody } from '../hooks/useSchemaApply';
import { useSchemaApply } from '../hooks/useSchemaApply';
import { useTypeEditorSave } from '../hooks/useTypeEditorSave';
import { useTypeImport } from '../hooks/useTypeImport';
import { useTypeSync } from '../hooks/useTypeSync';
import { useUnsavedGuard } from '../hooks/useUnsavedGuard';
import { updateType } from '../utils/api';
import type { DryRunReport, TypeRead } from '../utils/types';

const TYPES_LIST_HREF = '/admin/records/';

/** `Records/TypeEditor` — `/admin/records/types/new` and `/…/types/{key}`.
 *
 * The schema editor from design §6.1/§7.2/§16: type metadata, the field
 * list (with `indexed` — "the single most consequential choice on the
 * screen", §7.2 — named once in the Fields card header), the two field
 * pointers *below* it (UX review R19: on a new type they have nothing to
 * point at until a field exists), and, on an existing type, the danger zone.
 * Phase 3 lifts the Phase 1 lock: a populated type's `fields`,
 * `display_field` and `slug_field` are editable here too, checked by the
 * save itself, which the server enforces with a dry-run (§8.2) rather than
 * trusting the client to have run one. */
function TypeEditor({
  type,
  target_types,
  roles,
  public_route_prefix,
  content_locales,
  collections,
  tenant,
  tenancy_mode,
}: TypeEditorProps) {
  const { t } = useT();
  const isNew = type === null;
  const { current, externalChange, adopt, dirtyRef } = useTypeSync(type);
  const [values, setValues] = useState(metadataFrom(type));
  const [fields, setFields] = useState<EditableField[]>(() => withUids(type?.fields ?? []));
  // The dry-run report of the change last forced through (R7a) — the only
  // inventory of the records that force just marked invalid.
  const [lastApplied, setLastApplied] = useState<DryRunReport | null>(null);

  const applySaved = (saved: TypeRead) => {
    adopt(saved);
    setValues(metadataFrom(saved));
    setFields(withUids(saved.fields));
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

  const schemaDirty = !isNew && schemaIsDirty(current, values, fields);
  const dirty = typeIsDirty(current, values, fields);
  const guard = useUnsavedGuard(dirty);
  // Read by `useTypeSync`'s effect: a background reindex poll must not
  // re-baseline `current.version` under a draft (R15).
  dirtyRef.current = dirty;

  const { pending, createErrors, translatableError, save } = useTypeEditorSave({
    isNew,
    current,
    values,
    fields,
    guard,
    schemaApply,
    attemptUpdate,
    // The switch moved on click and the server refused, so it reverts
    // rather than sit disagreeing with the error under it (UX-7).
    onTranslatableRevert: () => {
      if (current) setValues((prev) => ({ ...prev, translatable: current.translatable }));
    },
    t,
  });

  const activeErrors = isNew ? createErrors : schemaApply.errors;
  // Three-way, not two: an error naming neither an input nor a row (a
  // `__root__` one) used to be handed to the field list and dropped there,
  // which is how a refused save came to change nothing at all (R6). `SaveBar`
  // renders what nothing else owns.
  const fieldKeys = fields.map((field) => field.key);
  const errorGroups = groupErrors(activeErrors, fieldKeys);

  /** Force a refused change through, keeping its report on screen after —
   *  `retryWith` answers `null` when the retry was itself refused. */
  const forceApply = async () => {
    const report = schemaApply.report;
    const result = await schemaApply.retryWith({ force: true });
    if (result) setLastApplied(report);
    return result;
  };

  // M3: a definition for *this* type is an ordinary schema update,
  // refusals and all; one naming another key creates that type.
  const { importDefinition } = useTypeImport({
    current,
    run: schemaApply.run,
    reset: schemaApply.reset,
    onCreated: (created) => {
      guard.allow();
      router.visit(`/admin/records/types/${created.key}`);
    },
  });

  const reloadFromConflict = (server: TypeRead) => {
    applySaved(server);
    schemaApply.reset();
  };

  const title = isNew
    ? t('records.type_editor.title_new', { defaultValue: 'New type' })
    : (current?.label ?? '');

  return (
    <>
      <Head
        title={
          isNew
            ? title
            : t('records.type_editor.title_edit', {
                defaultValue: 'Edit {label}',
                label: current?.label ?? '',
              })
        }
      />
      <PageShell
        title={title}
        actions={
          <>
            <TenantBadge tenant={tenant} tenancyMode={tenancy_mode} />
            <TypeIoMenu
              currentKey={current?.key ?? null}
              pending={pending || schemaApply.pending}
              onImport={importDefinition}
            />
            <Button variant="outline" onClick={() => router.visit(TYPES_LIST_HREF)}>
              {t('records.editor.cancel', { defaultValue: 'Cancel' })}
            </Button>
          </>
        }
      >
        <div className="space-y-6">
          {(schemaApply.versionConflict ?? externalChange) && (
            <TypeConflictNotice
              current={(schemaApply.versionConflict ?? externalChange) as TypeRead}
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
                roles={roles}
                values={values}
                onChange={(patch) => setValues((prev) => ({ ...prev, ...patch }))}
                errors={errorGroups.topLevel}
                publicRoutePrefix={public_route_prefix}
                contentLocales={content_locales}
                collections={collections}
                translatableError={translatableError}
                tenancyMode={tenancy_mode}
              />
            </CardContent>
          </Card>

          <FieldsCard
            current={current}
            isNew={isNew}
            fields={fields}
            targetTypes={target_types}
            displayField={values.displayField}
            slugField={values.slugField}
            disabled={pending}
            dirty={schemaDirty}
            errors={errorGroups.rows}
            lastApplied={lastApplied}
            onChange={setFields}
          />

          <PointerFields
            fields={fields}
            values={values}
            errors={errorGroups.topLevel}
            onChange={(patch) => setValues((prev) => ({ ...prev, ...patch }))}
          />

          <SaveBar
            errors={activeErrors}
            fieldKeys={fieldKeys}
            pending={pending}
            dirty={dirty}
            isNew={isNew}
            onSave={() => void save()}
          />

          {/* Below Save: the two 409 shapes a schema write can come back as,
              the type's schema history and the danger zone — the last two
              only for a type that has been created. */}
          <SchemaConflictPanel
            report={schemaApply.report}
            conflicts={schemaApply.conflicts}
            pending={schemaApply.pending || pending}
            onForce={forceApply}
            onOrphaned={(choice) => schemaApply.retryWith({ orphaned: choice })}
          />
          {!isNew && current && <TypeRevisions type={current} onRestored={applySaved} />}
          {!isNew && current && (
            <DeleteTypeSection
              type={current}
              onDeleted={() => {
                guard.allow();
                // U9: the module's most destructive action ended in silence —
                // seven records and a schema gone, with a missing row in a
                // table the operator may not be looking at as the only sign.
                toast.success(t('records.type_editor.deleted', { defaultValue: 'Type deleted' }));
                router.visit(TYPES_LIST_HREF);
              }}
            />
          )}
        </div>
      </PageShell>
    </>
  );
}

TypeEditor.layout = [RecordsLayout];
export default TypeEditor;
