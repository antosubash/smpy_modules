import { useT } from '@simple-module-py/i18n';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';

import { PAGE_SIZES } from '../utils/listing';

/** The per-page select — the same control in both of the footer's modes. */
export function PageSizeSelect({
  pageSize,
  loading,
  onPageSize,
}: {
  pageSize: number;
  loading: boolean;
  onPageSize: (size: number) => void;
}) {
  const { t } = useT();
  return (
    <div className="flex items-center gap-2">
      <Label htmlFor="records-page-size" className="font-normal">
        {t('records.records.page_size', { defaultValue: 'Per page' })}
      </Label>
      <NativeSelect
        id="records-page-size"
        className="w-auto"
        value={String(pageSize)}
        // Not `disabled` while loading: a focused control that disables
        // itself drops keyboard focus to <body> (see `PagerButton`).
        aria-disabled={loading || undefined}
        onChange={(e) => {
          if (!loading) onPageSize(Number(e.target.value));
        }}
      >
        {PAGE_SIZES.map((size) => (
          <NativeSelectOption key={size} value={String(size)}>
            {size}
          </NativeSelectOption>
        ))}
      </NativeSelect>
    </div>
  );
}
