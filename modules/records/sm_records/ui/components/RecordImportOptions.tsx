import { Button } from '@simple-module-py/ui/components/ui/button';
import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@simple-module-py/ui/components/ui/popover';
import { keys, useT } from '../utils/i18n';

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
  disabled = false,
}: {
  fields: FieldDef[];
  value: ImportOptionsValue;
  onChange: (patch: Partial<ImportOptionsValue>) => void;
  /** True while a check/apply is in flight — `RecordIoMenu` disables the
   *  trigger rather than hiding it, so the settings that produced the
   *  report on screen stay visible while it loads. */
  disabled?: boolean;
}) {
  const { t } = useT();
  const uniqueFields = fields.filter((field) => field.unique);

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          data-testid="records-import-options-trigger"
        >
          {t(keys.records.io.options)}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 space-y-3">
        <div className="grid gap-1.5">
          <Label htmlFor="records-import-mode">{t(keys.records.io.mode_label)}</Label>
          <NativeSelect
            id="records-import-mode"
            data-testid="records-import-mode"
            value={value.mode}
            onChange={(e) => onChange({ mode: e.target.value as ImportOptionsValue['mode'] })}
          >
            <NativeSelectOption value="upsert">{t(keys.records.io.mode_upsert)}</NativeSelectOption>
            <NativeSelectOption value="create">{t(keys.records.io.mode_create)}</NativeSelectOption>
            <NativeSelectOption value="update">{t(keys.records.io.mode_update)}</NativeSelectOption>
          </NativeSelect>
        </div>

        <div className="grid gap-1.5">
          <Label htmlFor="records-import-on-error">{t(keys.records.io.on_error_label)}</Label>
          <NativeSelect
            id="records-import-on-error"
            data-testid="records-import-on-error"
            value={value.onError}
            onChange={(e) => onChange({ onError: e.target.value as ImportOptionsValue['onError'] })}
          >
            <NativeSelectOption value="abort">
              {t(keys.records.io.on_error_abort)}
            </NativeSelectOption>
            <NativeSelectOption value="skip">{t(keys.records.io.on_error_skip)}</NativeSelectOption>
          </NativeSelect>
        </div>

        <div className="grid gap-1.5">
          <Label htmlFor="records-import-match-by">{t(keys.records.io.match_by_label)}</Label>
          <NativeSelect
            id="records-import-match-by"
            data-testid="records-import-match-by"
            value={value.matchBy}
            onChange={(e) => onChange({ matchBy: e.target.value })}
          >
            <NativeSelectOption value="uuid">{t(keys.records.io.match_by_uuid)}</NativeSelectOption>
            <NativeSelectOption value="slug">{t(keys.records.io.match_by_slug)}</NativeSelectOption>
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
              {t(keys.records.io.force_label)}
            </Label>
            <p className="text-xs text-muted-foreground">{t(keys.records.io.force_help)}</p>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
