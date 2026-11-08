/** One subscriber: fields, tags, unsubscribe, engagement and suppressions.
 *
 *  `suppressed` on the row means "this address will receive no newsletter mail"
 *  (suppressions are tenant-wide), so it is a plain statement here and never
 *  carries a reason. The Suppressions section lists only what the server returns
 *  for the lists the caller may read. A trashed subscriber has no actions. */

import { Link } from '@inertiajs/react';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@simple-module-py/ui/components/ui/alert-dialog';
import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@simple-module-py/ui/components/ui/sheet';
import { useEffect, useRef, useState } from 'react';

import { useListFields } from '../../hooks/useListFields';
import { useSubscriber } from '../../hooks/useSubscriber';
import { api, errorMessage } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
import type { Suppression } from '../../utils/types';
import { LiftDialog } from '../suppressions/LiftDialog';
import { REASON_LABELS } from '../suppressions/labels';
import { EngagementSummary } from './EngagementSummary';
import { SUBSCRIBER_STATUS_LABELS } from './SubscriberTable';
import { TagEditor } from './TagEditor';

const copy = keys.newsletter.subscribers;

interface Props {
  listKey: string;
  uuid: string | null;
  canEdit: boolean;
  canManage: boolean;
  onClose: () => void;
  onChanged: () => void;
}

export function SubscriberSheet({ listKey, uuid, canEdit, canManage, onClose, onChanged }: Props) {
  const { t, locale } = useT();
  const { detail, error: loadError, reload } = useSubscriber(listKey, uuid);
  const { fields } = useListFields(listKey);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [lifting, setLifting] = useState<Suppression | null>(null);
  const [liftDone, setLiftDone] = useState(false);
  // One action at a time: a repeat click while a request is in flight is dropped, so a
  // later 409 can never overwrite the first one's outcome.
  const inFlight = useRef(false);
  const [busy, setBusy] = useState(false);
  // biome-ignore lint/correctness/useExhaustiveDependencies: reset when another subscriber opens
  useEffect(() => {
    setLiftDone(false);
    setActionError(null);
    setLifting(null);
    setConfirming(false);
  }, [uuid]);

  const subscriber = detail?.subscriber ?? null;
  const choices = fields?.find((f) => f.key === 'tags')?.choices ?? [];
  const active = subscriber !== null && !subscriber.trashed;
  const errors = keys.newsletter.errors as Record<string, string>;

  const changed = () => {
    reload();
    onChanged();
  };
  const run = async (action: () => Promise<unknown>) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setActionError(null);
    try {
      await action();
    } catch (e) {
      setActionError(errorMessage(e, t));
    } finally {
      inFlight.current = false;
      setBusy(false);
      changed();
    }
  };
  const saveTags = (add: string[], remove: string[]) =>
    run(() => api.tagSubscriber(listKey, subscriber?.uuid ?? '', { add, remove }));
  const unsubscribe = async () => {
    setConfirming(false);
    await run(() => api.unsubscribeSubscriber(listKey, subscriber?.uuid ?? ''));
  };

  const date = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' });
  const error = actionError ?? loadError;

  return (
    <Sheet open={uuid !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="overflow-y-auto p-4 sm:max-w-lg">
        <SheetHeader className="p-0">
          <SheetTitle>{t(copy.detail.title)}</SheetTitle>
          <SheetDescription>{subscriber?.email ?? ''}</SheetDescription>
        </SheetHeader>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {liftDone && !error && (
          <p role="status" className="text-sm text-muted-foreground">
            {t(keys.newsletter.suppressions.lift.done)}
          </p>
        )}
        {subscriber && detail && (
          <div className="grid gap-5 text-sm">
            <div className="grid gap-1">
              <div className="font-medium">
                {[subscriber.first_name, subscriber.last_name].filter(Boolean).join(' ')}
              </div>
              <div className="flex flex-wrap gap-1">
                <Badge variant="outline">
                  {SUBSCRIBER_STATUS_LABELS[subscriber.status]
                    ? t(SUBSCRIBER_STATUS_LABELS[subscriber.status])
                    : subscriber.status}
                </Badge>
                {subscriber.suppressed && <Badge variant="destructive">{t(copy.suppressed)}</Badge>}
                {subscriber.trashed && <Badge variant="outline">{t(copy.trashed)}</Badge>}
              </div>
              {subscriber.confirmed_at && (
                <div className="text-muted-foreground">
                  {t(copy.confirmed_at)}: {date.format(new Date(subscriber.confirmed_at))}
                </div>
              )}
            </div>

            <section className="grid gap-2">
              <h3 className="font-medium">{t(copy.tags)}</h3>
              <TagEditor
                tags={subscriber.tags}
                choices={choices}
                disabled={!canEdit || !active}
                onSave={saveTags}
              />
            </section>

            {canManage && active && subscriber.status === 'confirmed' && (
              <div>
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={() => setConfirming(true)}
                >
                  {t(copy.detail.unsubscribe)}
                </Button>
              </div>
            )}

            <section className="grid gap-2">
              <h3 className="font-medium">{t(copy.detail.engagement)}</h3>
              <EngagementSummary engagement={detail.engagement} />
            </section>

            <section className="grid gap-2">
              <h3 className="font-medium">{t(copy.detail.suppressions)}</h3>
              {detail.suppressions.length === 0 && (
                <p className="text-muted-foreground">{t(copy.detail.suppressions_empty)}</p>
              )}
              {detail.suppressions.map((s) => (
                <div
                  key={s.id}
                  className="flex items-start justify-between gap-2 rounded-md border p-2"
                >
                  <div className="grid gap-0.5">
                    <span className="font-medium">
                      {t(REASON_LABELS[s.reason] ?? copy.detail.suppressions)}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {s.list_type_key || t(keys.newsletter.suppressions.all_lists)},{' '}
                      {date.format(new Date(s.created_at))}
                    </span>
                    {s.block && (
                      <span className="text-xs text-muted-foreground">
                        {t(errors[s.block] ?? keys.newsletter.errors.generic)}
                      </span>
                    )}
                  </div>
                  {canManage && active && s.block === null && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setLiftDone(false);
                        setLifting(s);
                      }}
                    >
                      {t(keys.newsletter.suppressions.lift.action)}
                    </Button>
                  )}
                </div>
              ))}
            </section>

            <Link href={detail.records_url} className="text-primary underline">
              {t(copy.edit_in_records)}
            </Link>
          </div>
        )}
      </SheetContent>

      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t(copy.unsubscribe_confirm.title)}</AlertDialogTitle>
            <AlertDialogDescription>
              {t(copy.unsubscribe_confirm.description, { email: subscriber?.email ?? '' })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t(copy.unsubscribe_confirm.keep)}</AlertDialogCancel>
            <AlertDialogAction disabled={busy} onClick={() => void unsubscribe()}>
              {t(copy.unsubscribe_confirm.confirm)}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {lifting && (
        <LiftDialog
          suppression={lifting}
          knownEmail={subscriber?.email}
          open
          onOpenChange={(o) => !o && setLifting(null)}
          onLifted={() => {
            setActionError(null);
            setLiftDone(true);
            changed();
          }}
          onStale={(message) => {
            setActionError(message);
            reload();
          }}
        />
      )}
    </Sheet>
  );
}
