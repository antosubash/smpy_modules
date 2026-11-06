/** Step 1: the list the import lands in, or a new one. */

import { Button } from '@simple-module-py/ui/components/ui/button';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { useState } from 'react';

import { keys, useT } from '../../utils/i18n';
import { CreateListDialog } from './CreateListDialog';

const copy = keys.newsletter.import;
const SELECT_ID = 'newsletter-import-list';

interface Props {
  lists: string[];
  value: string;
  disabled?: boolean;
  onChange: (key: string) => void;
  /** A list was created: the parent adds it to `lists` and selects it. */
  onCreated: (key: string) => void;
}

export function ListPicker({ lists, value, disabled, onChange, onCreated }: Props) {
  const { t } = useT();
  const [creating, setCreating] = useState(false);
  return (
    <div className="flex flex-wrap items-end gap-2">
      <div className="grid gap-2">
        <Label htmlFor={SELECT_ID}>{t(copy.list_label)}</Label>
        <NativeSelect
          id={SELECT_ID}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="">{t(copy.choose_list)}</option>
          {lists.map((key) => (
            <option key={key} value={key}>
              {key}
            </option>
          ))}
        </NativeSelect>
      </div>
      <Button type="button" variant="outline" disabled={disabled} onClick={() => setCreating(true)}>
        {t(copy.new_list)}
      </Button>
      {creating && <CreateListDialog open onOpenChange={setCreating} onCreated={onCreated} />}
    </div>
  );
}
