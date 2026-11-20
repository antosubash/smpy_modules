/** A calendar's subscriptions to external calendars. Opened by whoever may change the calendar's
 *  visibility (the server enforces it too). External events are read-only and never republished;
 *  the address is write-only and shown only masked. */
import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@simple-module-py/ui/components/ui/dialog';
import { useEffect, useRef, useState } from 'react';
import { useSubscriptions } from '../../hooks/useSubscriptions';
import type { Subscription } from '../../utils/api-subscriptions';
import { keys, useT } from '../../utils/i18n';
import { withName } from '../../utils/isolate';
import type { Calendar } from '../../utils/types';
import { SubscriptionForm } from './SubscriptionForm';
import { SubscriptionRow } from './SubscriptionRow';

type Form = { editing: Subscription | null } | null;

export function SubscriptionsDialog({
  calendar,
  canPublish,
  defaultMinutes,
  onGone,
}: {
  calendar: Calendar;
  canPublish: boolean;
  defaultMinutes: number;
  onGone?: () => void;
}) {
  const { t } = useT();
  const copy = keys.events.subscriptions;
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const [form, setForm] = useState<Form>(null);
  const [restore, setRestore] = useState(0);
  const wantFocus = useRef(false);
  const opener = useRef<HTMLElement | null>(null);
  const addButton = useRef<HTMLButtonElement>(null);
  /** Open the form from `from` (the Add button or a row's Edit) and remember it. */
  const openForm = (editing: Subscription | null, from: HTMLElement | null) => {
    opener.current = from;
    setForm({ editing });
  };
  /** Close the form and put focus back on the control that opened it (Add comes back with the
   *  form closed, so a detached opener falls back to it). */
  const closeForm = () => {
    setForm(null);
    wantFocus.current = true;
    setRestore((n) => n + 1);
  };
  // After the commit that removed the form, and again after each later commit until the list
  // that follows a save has arrived (the first subscription turns an empty list into one, and the
  // dialog takes focus for itself whenever the focused control goes away): focus goes to the
  // control that opened the form, or to the Add button that is in the document by then. It is
  // never taken from a control the person has moved to.
  useEffect(() => {
    if (!wantFocus.current) return;
    const active = document.activeElement;
    const stranded =
      !active || active === document.body || active.getAttribute('role') === 'dialog';
    if (stranded) {
      const back = opener.current?.isConnected ? opener.current : addButton.current;
      back?.focus();
    }
    if (!state.loading && restore > 0) wantFocus.current = false;
  });
  const state = useSubscriptions(calendar.id, open, onGone);
  const room = state.capacity;
  // Why Add is off: the calendar's, the member's or the tenant's allowance is used up.
  const full: string | null = !room
    ? null
    : room.calendar.used >= room.calendar.limit
      ? t(copy.limit_calendar, { limit: room.calendar.limit })
      : room.owner.used >= room.owner.limit
        ? t(copy.limit_owner, { limit: room.owner.limit })
        : room.tenant.used >= room.tenant.limit
          ? t(copy.limit_tenant, { limit: room.tenant.limit })
          : null;
  const change = (next: boolean) => {
    setOpen(next);
    if (!next) setForm(null); // an address typed and not saved is dropped with the dialog
  };
  return (
    <Dialog open={open} onOpenChange={change}>
      <DialogTrigger asChild>
        <Button
          ref={trigger}
          type="button"
          variant="outline"
          data-testid="events-subscriptions"
          aria-label={t(copy.trigger_for, { name: calendar.name })}
        >
          {t(copy.trigger)}
        </Button>
      </DialogTrigger>
      <DialogContent
        className="max-h-[calc(100dvh-2rem)] overflow-y-auto"
        data-testid="events-subscriptions-dialog"
        onEscapeKeyDown={(event) => {
          if (form) {
            event.preventDefault(); // the first Escape closes the form, the next the dialog
            closeForm();
          }
        }}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          trigger.current?.focus(); // back to where the person was
        }}
      >
        <DialogHeader>
          <DialogTitle>{withName(t, copy.title, calendar.name)}</DialogTitle>
          <DialogDescription className="dark:text-zinc-400">
            {t(copy.description)}
          </DialogDescription>
        </DialogHeader>
        {state.loading && state.items.length === 0 ? <p role="status">{t(copy.loading)}</p> : null}
        {state.error ? (
          <p role="alert" className="text-destructive dark:text-red-400">
            {state.error}
          </p>
        ) : null}
        {!state.loading && !state.error && state.items.length === 0 && !form ? (
          <p>{t(copy.none)}</p>
        ) : null}
        <ul className="space-y-2">
          {state.items.map((sub) => (
            <SubscriptionRow
              key={sub.id}
              sub={sub}
              calendarColor={calendar.color}
              error={state.rowError[sub.id]}
              note={state.notes[sub.id]}
              onAction={(action) => state.act(sub.id, action)}
              onEdit={(from) => openForm(sub, from)}
            />
          ))}
        </ul>
        {form ? (
          <SubscriptionForm
            key={form.editing?.id ?? 'new'}
            calendarId={calendar.id}
            editing={form.editing}
            isPublicCalendar={calendar.visibility === 'public'}
            canPublish={canPublish}
            defaultMinutes={defaultMinutes}
            onDone={() => {
              closeForm();
              void state.reload();
            }}
            onCancel={closeForm}
          />
        ) : (
          <>
            <Button
              ref={addButton}
              type="button"
              disabled={full !== null}
              aria-describedby={full ? 'events-sub-full' : undefined}
              onClick={(e) => openForm(null, e.currentTarget)}
            >
              {t(copy.add)}
            </Button>
            {full ? (
              <p id="events-sub-full" className="text-sm text-muted-foreground dark:text-zinc-400">
                {full}
              </p>
            ) : null}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
