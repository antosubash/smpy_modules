import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';

import { useT } from '../../utils/i18n';
import { VISIBILITIES, visibilityLabel } from '../../utils/labels';
import type { Visibility } from '../../utils/types';

/** The visibility choice. Internal and public need `images.publish`; without it
 *  they are listed but disabled, unless already the current value. */
export function VisibilitySelect({
  id,
  value,
  canPublish,
  disabled,
  onChange,
}: {
  id: string;
  value: Visibility;
  canPublish: boolean;
  disabled?: boolean;
  onChange: (next: Visibility) => void;
}) {
  const { t } = useT();
  return (
    <NativeSelect
      id={id}
      value={value}
      disabled={disabled}
      data-testid="images-visibility"
      onChange={(e) => onChange(e.target.value as Visibility)}
    >
      {VISIBILITIES.map((option) => (
        <option
          key={option}
          value={option}
          disabled={option !== 'private' && !canPublish && option !== value}
        >
          {visibilityLabel(t, option)}
        </option>
      ))}
    </NativeSelect>
  );
}
