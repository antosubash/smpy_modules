import { useT } from '@simple-module-py/i18n';
import { Card, CardContent, CardHeader, CardTitle } from '@simple-module-py/ui/components/ui/card';

import type { DryRunReport, TypeRead, ValidationError } from '../../utils/types';
import { FieldList } from './FieldList';
import { LastAppliedReport } from './LastAppliedReport';
import { SchemaPreviewPanel } from './SchemaPreviewPanel';
import type { EditableField, TargetType } from './types';

/**
 * The schema editor's Fields card: the list itself, the two dry-run buttons
 * under it, and the report of the last change that was forced through.
 *
 * Split out of `TypeEditor` for the 300-line cap. The `indexed` hint lives in
 * this header and nowhere else (UX review R23): it used to repeat inside
 * every field row, which on a thirteen-field type is where it stopped being
 * read.
 */
export function FieldsCard({
  current,
  isNew,
  fields,
  originalKeys,
  targetTypes,
  displayField,
  slugField,
  disabled,
  dirty,
  errors,
  lastApplied,
  onChange,
}: {
  current: TypeRead | null;
  isNew: boolean;
  fields: EditableField[];
  originalKeys: ReadonlySet<string>;
  targetTypes: TargetType[];
  displayField: string;
  slugField: string;
  disabled: boolean;
  dirty: boolean;
  errors: ValidationError[];
  lastApplied: DryRunReport | null;
  onChange: (next: EditableField[]) => void;
}) {
  const { t } = useT();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('records.type_editor.section_fields', { defaultValue: 'Fields' })}</CardTitle>
        <p className="text-sm text-muted-foreground">
          {t('records.type_editor.field_indexed_hint', {
            defaultValue:
              'The single most consequential choice on this screen: filterable and sortable, at the cost of a write per save.',
          })}
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {!isNew && current && (
          <p className="text-sm text-muted-foreground">
            {t('records.type_editor.live_notice', {
              count: current.record_count,
              trashed: current.trashed_record_count,
              defaultValue:
                '{count} live, {trashed} trashed records — changes are checked against them before they apply.',
            })}
          </p>
        )}
        <FieldList
          fields={fields}
          originalKeys={originalKeys}
          targetTypes={targetTypes}
          disabled={disabled}
          errors={errors}
          onChange={onChange}
        />
        {!isNew && current && (
          <>
            <SchemaPreviewPanel
              typeKey={current.key}
              saved={current}
              fields={fields}
              displayField={displayField}
              slugField={slugField}
              dirty={dirty}
            />
            <LastAppliedReport report={lastApplied} typeKey={current.key} />
          </>
        )}
      </CardContent>
    </Card>
  );
}
