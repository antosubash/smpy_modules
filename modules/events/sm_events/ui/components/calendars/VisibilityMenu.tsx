import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@simple-module-py/ui/components/ui/dialog';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { type FormEvent, useState } from 'react';
import { errorText, setVisibility } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
import type { Calendar, Visibility } from '../../utils/types';

export function VisibilityMenu({ calendar, onSaved }: { calendar: Calendar; onSaved: () => void }) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState<Visibility>(calendar.visibility);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      await setVisibility(calendar.id, value);
      onSaved();
      setOpen(false);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setPending(false);
    }
  }
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!pending) {
          setOpen(next);
          setError(null);
          setValue(calendar.visibility);
        }
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline">{t(keys.events.calendars.visibility)}</Button>
      </DialogTrigger>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto" showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>{t(keys.events.calendars.visibility)}</DialogTitle>
          <DialogDescription>{t(keys.events.calendars.visibility_description)}</DialogDescription>
        </DialogHeader>
        <form onSubmit={save} className="grid gap-4">
          <Label htmlFor="visibility-value">{t(keys.events.calendars.visibility)}</Label>
          <NativeSelect
            id="visibility-value"
            value={value}
            onChange={(e) => setValue(e.target.value as Visibility)}
          >
            {(['private', 'internal', 'public'] as const).map((v) => (
              <option key={v} value={v}>
                {t(keys.events.visibility[v])}
              </option>
            ))}
          </NativeSelect>
          {error && (
            <p role="alert" className="text-destructive">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <DialogClose asChild>
              <Button type="button" disabled={pending} variant="outline">
                {t(keys.events.common.cancel)}
              </Button>
            </DialogClose>
            <Button disabled={pending}>{t(keys.events.common.save)}</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
