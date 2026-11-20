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
import { Label } from '@simple-module-py/ui/components/ui/label';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';
import { type FormEvent, useState } from 'react';
import type { Outcome } from '../../hooks/useEventActions';
import { useFormErrors } from '../../hooks/useFormErrors';
import { useRequestScope } from '../../hooks/useRequestScope';
import { fieldErrorId, invalidProps, requiredText } from '../../utils/field-errors';
import { keys, useT } from '../../utils/i18n';
import type { WorkflowBody } from '../../utils/types-events';

const SHOWN = ['note'] as const;

type Reject = (
  body: Omit<WorkflowBody, 'expected_revision'>,
  onError: (e: unknown) => void,
) => Promise<Outcome>;

/** Reject a submitted event back to draft. The note says what to change and is
 *  kept in the history, so it is required. */
export function RejectDialog({ disabled, onReject }: { disabled: boolean; onReject: Reject }) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" disabled={disabled}>
          {t(keys.events.workflow.reject)}
        </Button>
      </DialogTrigger>
      {open && <RejectForm onReject={onReject} onDone={() => setOpen(false)} />}
    </Dialog>
  );
}

function RejectForm({ onReject, onDone }: { onReject: Reject; onDone: () => void }) {
  const { t } = useT();
  const copy = keys.events.workflow;
  const [note, setNote] = useState('');
  const [pending, setPending] = useState(false);
  const errors = useFormErrors(undefined, undefined, SHOWN);
  const begin = useRequestScope(true);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    errors.reset();
    if (!note.trim()) return errors.reject({ note: requiredText() });
    const request = begin();
    setPending(true);
    const outcome = await onReject({ note: note.trim() }, (e) => request.alive() && errors.fail(e));
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
        <DialogTitle>{t(copy.reject_title)}</DialogTitle>
        <DialogDescription>{t(copy.reject_description)}</DialogDescription>
      </DialogHeader>
      <form ref={errors.formRef} className="grid gap-4" noValidate onSubmit={submit}>
        <div className="grid gap-2">
          <Label htmlFor="reject-note">{t(copy.reject_note)}</Label>
          <Textarea
            id="reject-note"
            required
            maxLength={1000}
            value={note}
            {...invalidProps('reject-note', errors.fields.note)}
            onChange={(e) => {
              setNote(e.target.value);
              errors.clearField('note');
            }}
          />
          <FieldError id={fieldErrorId('reject-note')}>{errors.fields.note}</FieldError>
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
            {t(pending ? keys.events.common.saving : copy.reject_apply)}
          </Button>
        </div>
      </form>
    </DialogContent>
  );
}
