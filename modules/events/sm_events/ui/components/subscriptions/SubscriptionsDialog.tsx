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
import { useState } from 'react';
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
  const [form, setForm] = useState<Form>(null);
  const state = useSubscriptions(calendar.id, open, onGone);
  const change = (next: boolean) => {
    setOpen(next);
    if (!next) setForm(null); // an address typed and not saved is dropped with the dialog
  };
  return (
    <Dialog open={open} onOpenChange={change}>
      <DialogTrigger asChild>
        <Button
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
      >
        <DialogHeader>
          <DialogTitle>{withName(t, copy.title, calendar.name)}</DialogTitle>
          <DialogDescription>{t(copy.description)}</DialogDescription>
        </DialogHeader>
        {state.loading && state.items.length === 0 ? <p role="status">{t(copy.loading)}</p> : null}
        {state.error ? (
          <p role="alert" className="text-destructive">
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
              onEdit={() => setForm({ editing: sub })}
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
              setForm(null);
              void state.reload();
            }}
            onCancel={() => setForm(null)}
          />
        ) : (
          <Button type="button" onClick={() => setForm({ editing: null })}>
            {t(copy.add)}
          </Button>
        )}
      </DialogContent>
    </Dialog>
  );
}
