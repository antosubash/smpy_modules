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
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { type FormEvent, useState } from 'react';
import type { Outcome } from '../../hooks/useEventActions';
import { useFormErrors } from '../../hooks/useFormErrors';
import { useRequestScope } from '../../hooks/useRequestScope';
import { ApiError, CODE } from '../../utils/api';
import { fieldErrorId, invalidProps, requiredText } from '../../utils/field-errors';
import { keys, useT } from '../../utils/i18n';
import type { WorkflowBody } from '../../utils/types-events';

const SHOWN = ['publish_at_local'] as const;
const NOW = 'now';
const LATER = 'later';
const codeField = (e: unknown) =>
  e instanceof ApiError && e.code === CODE.invalidLocalTime ? 'publish_at_local' : undefined;

type Approve = (
  body: Omit<WorkflowBody, 'expected_revision'>,
  onError: (e: unknown) => void,
) => Promise<Outcome>;

/** Approve: publish now, or at a wall-clock time on the event's own clock. The
 *  time goes to the server as typed; the browser never converts it. */
export function ScheduleDialog({
  disabled,
  timezone,
  onApprove,
}: {
  disabled: boolean;
  timezone: string;
  onApprove: Approve;
}) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button disabled={disabled}>{t(keys.events.workflow.approve)}</Button>
      </DialogTrigger>
      {open && (
        <ScheduleForm timezone={timezone} onApprove={onApprove} onDone={() => setOpen(false)} />
      )}
    </Dialog>
  );
}

function ScheduleForm({
  timezone,
  onApprove,
  onDone,
}: {
  timezone: string;
  onApprove: Approve;
  onDone: () => void;
}) {
  const { t } = useT();
  const copy = keys.events.workflow;
  const [when, setWhen] = useState(NOW);
  const [at, setAt] = useState('');
  const [pending, setPending] = useState(false);
  const errors = useFormErrors(undefined, undefined, SHOWN, codeField);
  const begin = useRequestScope(true);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    errors.reset();
    if (when === LATER && !at) return errors.reject({ publish_at_local: requiredText() });
    const request = begin();
    setPending(true);
    const outcome = await onApprove(
      when === LATER ? { publish_at_local: at } : {},
      (e) => request.alive() && errors.fail(e),
    );
    if (!request.alive()) return;
    setPending(false);
    if (outcome !== 'failed') onDone();
  }
  return (
    <DialogContent
      className="max-h-[calc(100dvh-2rem)] overflow-y-auto"
      showCloseButton={false}
      onEscapeKeyDown={(e) => pending && e.preventDefault()}
      onInteractOutside={(e) => pending && e.preventDefault()}
    >
      <DialogHeader>
        <DialogTitle>{t(copy.approve_title)}</DialogTitle>
        <DialogDescription className="dark:text-zinc-400">
          {t(copy.approve_description, { timezone })}
        </DialogDescription>
      </DialogHeader>
      <form ref={errors.formRef} className="grid gap-4" noValidate onSubmit={submit}>
        <div className="grid gap-2">
          <Label htmlFor="schedule-when">{t(copy.when)}</Label>
          <NativeSelect id="schedule-when" value={when} onChange={(e) => setWhen(e.target.value)}>
            <option value={NOW}>{t(copy.now)}</option>
            <option value={LATER}>{t(copy.later)}</option>
          </NativeSelect>
        </div>
        {when === LATER && (
          <div className="grid gap-2">
            <Label htmlFor="schedule-at">{t(copy.at)}</Label>
            <Input
              id="schedule-at"
              type="datetime-local"
              required
              value={at}
              {...invalidProps('schedule-at', errors.fields.publish_at_local)}
              onChange={(e) => {
                setAt(e.target.value);
                errors.clearField('publish_at_local');
              }}
            />
            <FieldError id={fieldErrorId('schedule-at')}>
              {errors.fields.publish_at_local}
            </FieldError>
          </div>
        )}
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
            {t(pending ? keys.events.common.saving : copy.approve_apply)}
          </Button>
        </div>
      </form>
    </DialogContent>
  );
}
