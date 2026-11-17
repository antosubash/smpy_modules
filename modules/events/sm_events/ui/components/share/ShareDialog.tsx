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
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { useState } from 'react';
import { toast } from 'sonner';

import { MIN_QUERY, useShares } from '../../hooks/useShares';
import { errorText } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
import { Name } from '../../utils/isolate';
import type { Share, ShareCandidate, ShareRole } from '../../utils/types';

function roleLabel(t: ReturnType<typeof useT>['t'], role: string): string {
  return role === 'edit' ? t(keys.events.share.role_edit) : t(keys.events.share.role_view);
}

/** Share a calendar: who has access now, a picker for who could, and a role
 *  (view or edit). The owner (or `events.manage`) opens it; the server enforces
 *  that again on every call. */
export function ShareDialog({
  calendarId,
  calendarName,
  onGone,
}: {
  calendarId: string;
  calendarName?: string;
  /** The calendar was trashed or deleted elsewhere: refresh the list. */
  onGone?: () => void;
}) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [role, setRole] = useState<ShareRole>('view');
  const state = useShares(calendarId, open, onGone);

  const report = (e: unknown) => toast.error(errorText(e, keys.events.errors.calendar_gone));

  const grant = async (candidate: ShareCandidate) => {
    try {
      await state.grant(candidate, role);
      toast(t(keys.events.share.granted, { name: candidate.display_name }));
    } catch (e) {
      report(e);
    }
  };

  const revoke = async (share: Share) => {
    try {
      await state.revoke(share);
      toast(t(keys.events.share.revoked));
    } catch (e) {
      report(e);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          type="button"
          variant="outline"
          data-testid="events-share"
          aria-label={
            calendarName ? t(keys.events.calendars.share_for, { name: calendarName }) : undefined
          }
        >
          {t(keys.events.share.button)}
        </Button>
      </DialogTrigger>
      <DialogContent
        className="max-h-[calc(100dvh-2rem)] overflow-y-auto"
        showCloseButton={false}
        data-testid="events-share-dialog"
      >
        <DialogHeader>
          <DialogTitle>{t(keys.events.share.title)}</DialogTitle>
          <DialogDescription>{t(keys.events.share.description)}</DialogDescription>
        </DialogHeader>

        <section className="space-y-2" aria-label={t(keys.events.share.current)}>
          <h3 className="text-sm font-medium">{t(keys.events.share.current)}</h3>
          {state.listError && !state.loading && (
            <div
              className="flex items-center justify-between gap-2"
              data-testid="events-share-list-error"
            >
              <p className="text-sm text-destructive" role="alert">
                {state.listError}
              </p>
              <Button type="button" variant="outline" size="sm" onClick={state.retry}>
                {t(keys.events.common.retry)}
              </Button>
            </div>
          )}
          {state.shares.length === 0 ? (
            !state.loading && state.listError ? null : (
              <p className="text-sm text-muted-foreground">
                {t(state.loading ? keys.events.common.loading : keys.events.share.none)}
              </p>
            )
          ) : (
            <ul className="divide-y rounded-md border">
              {state.shares.map((share) => {
                const name = share.subject_label ?? share.subject_id;
                return (
                  <li
                    key={share.id}
                    className="flex items-center justify-between gap-2 px-3 py-2 text-sm"
                    data-testid="events-share-row"
                  >
                    <span className="min-w-0 break-words">
                      <Name>{name}</Name> · {roleLabel(t, share.role)}
                      {share.expired ? ` · ${t(keys.events.share.expired)}` : ''}
                    </span>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      aria-label={t(keys.events.share.revoke_for, { name })}
                      onClick={() => void revoke(share)}
                    >
                      {t(keys.events.share.revoke)}
                    </Button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section className="space-y-2">
          <div className="grid gap-2">
            <Label htmlFor="events-share-search">{t(keys.events.share.search_label)}</Label>
            <Input
              id="events-share-search"
              data-testid="events-share-search"
              maxLength={100}
              type="search"
              value={state.query}
              placeholder={t(keys.events.share.search_placeholder)}
              onChange={(e) => state.setQuery(e.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="events-share-role">{t(keys.events.share.role)}</Label>
            <NativeSelect
              id="events-share-role"
              value={role}
              onChange={(e) => setRole(e.target.value as ShareRole)}
            >
              <option value="view">{t(keys.events.share.role_view)}</option>
              <option value="edit">{t(keys.events.share.role_edit)}</option>
            </NativeSelect>
          </div>
          {state.tooShort ? (
            <p className="text-sm text-muted-foreground" data-testid="events-share-hint">
              {t(keys.events.share.search_min, { min: MIN_QUERY })}
            </p>
          ) : state.searchError ? null : !state.searchSettled ? null : state.candidates.length ===
            0 ? (
            <p className="text-sm text-muted-foreground">{t(keys.events.share.no_candidates)}</p>
          ) : (
            <ul className="max-h-48 divide-y overflow-auto rounded-md border">
              {state.candidates.map((candidate) => (
                <li
                  key={candidate.id}
                  className="flex items-center justify-between gap-2 px-3 py-2 text-sm"
                  data-testid="events-share-candidate"
                >
                  <span className="min-w-0 break-words">
                    <Name>{candidate.display_name}</Name>
                    <span className="block text-xs text-muted-foreground">{candidate.email}</span>
                  </span>
                  <Button
                    type="button"
                    size="sm"
                    aria-label={t(keys.events.share.grant_for, { name: candidate.display_name })}
                    onClick={() => void grant(candidate)}
                  >
                    {t(keys.events.share.grant)}
                  </Button>
                </li>
              ))}
            </ul>
          )}
          {state.searchError && (
            <p className="text-sm text-destructive" role="alert">
              {state.searchError}
            </p>
          )}
        </section>
        <DialogClose asChild>
          <Button variant="outline">{t(keys.events.common.close)}</Button>
        </DialogClose>
      </DialogContent>
    </Dialog>
  );
}
