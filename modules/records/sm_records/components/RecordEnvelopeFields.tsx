import { useT } from '@simple-module-py/i18n';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';

import type { RecordStatus, ValidationError } from '../utils/types';

const SLUG_ID = 'record-slug';
const POSITION_ID = 'record-position';
const STATUS_ID = 'record-status';

function fieldMessage(errors: ValidationError[], field: string): string | undefined {
  return errors.find((e) => e.field === field)?.message;
}

/** The three record-level inputs that sit outside the schema form —
 *  `status`/`slug`/`position` — split out of `RecordEditor` to keep that
 *  page under the 300-line cap. */
export function RecordEnvelopeFields({
  status,
  slug,
  position,
  envelope,
  onStatusChange,
  onSlugChange,
  onPositionChange,
}: {
  status: RecordStatus;
  slug: string;
  position: string;
  envelope: ValidationError[];
  onStatusChange: (next: RecordStatus) => void;
  onSlugChange: (next: string) => void;
  onPositionChange: (next: string) => void;
}) {
  const { t } = useT();
  return (
    <div className="grid gap-4 sm:grid-cols-3">
      <div className="grid gap-1.5">
        <Label htmlFor={STATUS_ID}>{t('records.records.status', { defaultValue: 'Status' })}</Label>
        <NativeSelect
          id={STATUS_ID}
          className="w-full"
          value={status}
          onChange={(e) => onStatusChange(e.target.value as RecordStatus)}
        >
          <NativeSelectOption value="draft">
            {t('records.records.draft', { defaultValue: 'Draft' })}
          </NativeSelectOption>
          <NativeSelectOption value="published">
            {t('records.records.published', { defaultValue: 'Published' })}
          </NativeSelectOption>
        </NativeSelect>
        {fieldMessage(envelope, 'status') && (
          <p className="text-sm text-destructive">{fieldMessage(envelope, 'status')}</p>
        )}
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor={SLUG_ID}>{t('records.editor.slug_label', { defaultValue: 'Slug' })}</Label>
        <Input id={SLUG_ID} value={slug} onChange={(e) => onSlugChange(e.target.value)} />
        {fieldMessage(envelope, 'slug') && (
          <p className="text-sm text-destructive">{fieldMessage(envelope, 'slug')}</p>
        )}
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor={POSITION_ID}>
          {t('records.editor.position_label', { defaultValue: 'Position' })}
        </Label>
        <Input
          id={POSITION_ID}
          type="number"
          value={position}
          onChange={(e) => onPositionChange(e.target.value)}
        />
        {fieldMessage(envelope, 'position') && (
          <p className="text-sm text-destructive">{fieldMessage(envelope, 'position')}</p>
        )}
      </div>
    </div>
  );
}
