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
import { FieldError } from '@simple-module-py/ui/components/ui/field';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';
import { type FormEvent, useState } from 'react';
import type { Outcome } from '../../hooks/useEventActions';
import { useFormErrors } from '../../hooks/useFormErrors';
import { useRequestScope } from '../../hooks/useRequestScope';
import { ApiError } from '../../utils/api';
import { fieldErrorId, invalidProps, requiredText } from '../../utils/field-errors';
import { keys, useT } from '../../utils/i18n';
import type { OverrideInput } from '../../utils/types-events';

const SHOWN = ['start', 'end', 'note'] as const;
const AT: Record<string, string> = {
  invalid_local_time: 'start',
  end_before_start: 'end',
  duration_too_long: 'end',
};
const codeField = (e: unknown) => (e instanceof ApiError ? (e.field ?? AT[e.code]) : undefined);

type SetOverride = (
  input: Omit<OverrideInput, 'expected_revision'>,
  onError?: (e: unknown) => void,
) => Promise<Outcome>;

/** Move one occurrence: its new start and end on the event's own clock. Only the
 *  times can move; a change to the title or place is a change to the series. */
export function OverrideDialog({
  originalStart,
  label,
  start,
  end,
  allDay,
  timezone,
  disabled,
  onSet,
}: {
  originalStart: string;
  /** The occurrence as the row names it, for the accessible name. */
  label: string;
  start: string;
  end: string;
  allDay: boolean;
  timezone: string;
  disabled: boolean;
  onSet: SetOverride;
}) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          disabled={disabled}
          aria-label={t(keys.events.preview.move_for, { when: label })}
        >
          {t(keys.events.preview.move)}
        </Button>
      </DialogTrigger>
      {open && (
        <MoveForm
          originalStart={originalStart}
          start={start}
          end={end}
          allDay={allDay}
          timezone={timezone}
          onSet={onSet}
          onDone={() => setOpen(false)}
        />
      )}
    </Dialog>
  );
}

function MoveForm({
  originalStart,
  start,
  end,
  allDay,
  timezone,
  onSet,
  onDone,
}: {
  originalStart: string;
  start: string;
  end: string;
  allDay: boolean;
  timezone: string;
  onSet: SetOverride;
  onDone: () => void;
}) {
  const { t } = useT();
  const copy = keys.events.preview;
  const [from, setFrom] = useState(start);
  const [to, setTo] = useState(end);
  const [note, setNote] = useState('');
  const [pending, setPending] = useState(false);
  const errors = useFormErrors(undefined, undefined, SHOWN, codeField);
  const begin = useRequestScope(true);
  const type = allDay ? 'date' : 'datetime-local';
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    errors.reset();
    const found: Record<string, string> = {};
    if (!from) found.start = requiredText();
    if (!to) found.end = requiredText();
    if (Object.keys(found).length > 0) return errors.reject(found);
    const request = begin();
    setPending(true);
    const outcome = await onSet(
      {
        original_start: originalStart,
        kind: 'moved',
        start: from,
        end: to,
        note: note.trim() || null,
      },
      (e) => request.alive() && errors.fail(e),
    );
    if (!request.alive()) return;
    setPending(false);
    if (outcome !== 'failed') onDone();
  }
  const box = (
    id: string,
    name: 'start' | 'end',
    value: string,
    set: (v: string) => void,
    label: string,
  ) => (
    <div className="grid gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type={type}
        required
        value={value}
        {...invalidProps(id, errors.fields[name])}
        onChange={(e) => {
          set(e.target.value);
          errors.clearField(name);
        }}
      />
      <FieldError id={fieldErrorId(id)}>{errors.fields[name]}</FieldError>
    </div>
  );
  return (
    <DialogContent
      className="max-h-[calc(100dvh-2rem)] overflow-y-auto"
      showCloseButton={false}
      onEscapeKeyDown={(e) => pending && e.preventDefault()}
      onInteractOutside={(e) => pending && e.preventDefault()}
    >
      <DialogHeader>
        <DialogTitle>{t(copy.move_title)}</DialogTitle>
        <DialogDescription>{t(copy.move_description, { timezone })}</DialogDescription>
      </DialogHeader>
      <form ref={errors.formRef} className="grid gap-4" noValidate onSubmit={submit}>
        {box('move-start', 'start', from, setFrom, t(keys.events.editor.start))}
        {box(
          'move-end',
          'end',
          to,
          setTo,
          t(allDay ? keys.events.editor.last_day : keys.events.editor.end),
        )}
        <div className="grid gap-2">
          <Label htmlFor="move-note">{t(copy.note)}</Label>
          <Textarea
            id="move-note"
            maxLength={1000}
            value={note}
            {...invalidProps('move-note', errors.fields.note)}
            onChange={(e) => {
              setNote(e.target.value);
              errors.clearField('note');
            }}
          />
          <FieldError id={fieldErrorId('move-note')}>{errors.fields.note}</FieldError>
        </div>
        {errors.error && (
          <p role="alert" className="text-destructive dark:text-red-400">
            {errors.error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <DialogClose asChild>
            <Button type="button" variant="outline" disabled={pending}>
              {t(keys.events.common.cancel)}
            </Button>
          </DialogClose>
          <Button disabled={pending}>
            {t(pending ? keys.events.common.saving : copy.move_apply)}
          </Button>
        </div>
      </form>
    </DialogContent>
  );
}
