import { Button } from '@simple-module-py/ui/components/ui/button';
import { type ComponentType, useState } from 'react';

import { keys, useT } from '../../utils/i18n';

export interface PickedImage {
  url: string;
  altText?: string;
}
interface PickerDialogProps {
  open: boolean;
  onClose: () => void;
  onSelect: (image: PickedImage) => void;
}

let PickerDialog: ComponentType<PickerDialogProps> | undefined;

/** Registered at boot only by the optional pagebuilder-blocks.ts entry. */
export function registerMediaPicker(dialog: ComponentType<PickerDialogProps>) {
  PickerDialog = dialog;
}

export function MediaPickerButton({
  enabled,
  disabled = false,
  onSelect,
}: {
  enabled: boolean;
  disabled?: boolean;
  onSelect: (image: PickedImage) => void;
}) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  if (!enabled || !PickerDialog) return null;
  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled}
        onClick={() => setOpen(true)}
      >
        {t(keys.news.media_picker.browse)}
      </Button>
      <PickerDialog
        open={open && !disabled}
        onClose={() => setOpen(false)}
        onSelect={(image) => {
          if (!disabled) onSelect(image);
          setOpen(false);
        }}
      />
    </>
  );
}
