import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@simple-module-py/ui/components/ui/popover';

import type { FieldDef } from '../utils/types';

export type ImportOptionsValue = {
  mode: 'upsert' | 'create' | 'update';
  onError: 'abort' | 'skip';
  /** `'uuid'`, `'slug'`, or one of `fields`' unique keys — see
   *  `services/_import_match.py::match_field`. */
  matchBy: string;
  force: boolean;
};

export const DEFAULT_IMPORT_OPTIONS: ImportOptionsValue = {
  mode: 'upsert',
  onError: 'abort',
  matchBy: 'uuid',
  force: false,
};

/** The four knobs `POST .../records/import` takes beyond the file itself
 *  (FAIL-1's UI half): the API always accepted them, but `RecordIoMenu`
 *  exposed none, so a bulk edit that needed `force` — or any other choice
 *  here — could not be finished from the browser. Kept in a popover rather
 *  than inline: these are occasional, not the toolbar's everyday shape. */
export function RecordImportOptions({
  fields,
  value,
  onChange,
}: {
  fields: FieldDef[];
  value: ImportOptionsValue;
  onChange: (patch: Partial<ImportOptionsValue>) => void;
}) {
  const { t } = useT();
  const uniqueFields = fields.filter((field) => field.unique);

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          data-testid="records-import-options-trigger"
        >
          {t('records.io.options', { defaultValue: 'Import options' })}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 space-y-3">
        <div className="grid gap-1.5">
          <Label htmlFor="records-import-mode">
            {t('records.io.mode_label', { defaultValue: 'Mode' })}
          </Label>
          <NativeSelect
            id="records-import-mode"
            data-testid="records-import-mode"
            value={value.mode}
            onChange={(e) => onChange({ mode: e.target.value as ImportOptionsValue['mode'] })}
          >
            <NativeSelectOption value="upsert">
              {t('records.io.mode_upsert', { defaultValue: 'Create or update (upsert)' })}
            </NativeSelectOption>
            <NativeSelectOption value="create">
              {t('records.io.mode_create', { defaultValue: 'Create only' })}
            </NativeSelectOption>
            <NativeSelectOption value="update">
              {t('records.io.mode_update', { defaultValue: 'Update only' })}
            </NativeSelectOption>
          </NativeSelect>
        </div>

        <div className="grid gap-1.5">
          <Label htmlFor="records-import-on-error">
            {t('records.io.on_error_label', { defaultValue: 'If a row fails' })}
          </Label>
          <NativeSelect
            id="records-import-on-error"
            data-testid="records-import-on-error"
            value={value.onError}
            onChange={(e) => onChange({ onError: e.target.value as ImportOptionsValue['onError'] })}
          >
            <NativeSelectOption value="abort">
              {t('records.io.on_error_abort', { defaultValue: 'Stop and write nothing' })}
            </NativeSelectOption>
            <NativeSelectOption value="skip">
              {t('records.io.on_error_skip', { defaultValue: 'Skip it and write the rest' })}
            </NativeSelectOption>
          </NativeSelect>
        </div>

        <div className="grid gap-1.5">
          <Label htmlFor="records-import-match-by">
            {t('records.io.match_by_label', { defaultValue: 'Match existing records by' })}
          </Label>
          <NativeSelect
            id="records-import-match-by"
            data-testid="records-import-match-by"
            value={value.matchBy}
            onChange={(e) => onChange({ matchBy: e.target.value })}
          >
            <NativeSelectOption value="uuid">
              {t('records.io.match_by_uuid', { defaultValue: 'uuid' })}
            </NativeSelectOption>
            <NativeSelectOption value="slug">
              {t('records.io.match_by_slug', { defaultValue: 'slug' })}
            </NativeSelectOption>
            {uniqueFields.map((field) => (
              <NativeSelectOption key={field.key} value={field.key}>
                {field.label} ({field.key})
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </div>

        <div className="flex items-start gap-2">
          <Checkbox
            id="records-import-force"
            data-testid="records-import-force"
            checked={value.force}
            onCheckedChange={(checked) => onChange({ force: checked === true })}
          />
          <div className="grid gap-1">
            <Label htmlFor="records-import-force" className="font-normal">
              {t('records.io.force_label', { defaultValue: 'Overwrite unversioned rows' })}
            </Label>
            <p className="text-xs text-muted-foreground">
              {t('records.io.force_help', {
                defaultValue: 'Overwrite records whose version the file does not carry.',
              })}
            </p>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
