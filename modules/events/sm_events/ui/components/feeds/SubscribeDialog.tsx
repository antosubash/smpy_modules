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
import { toast } from 'sonner';
import { useFeedTokens } from '../../hooks/useFeedTokens';
import { SubscribeBox } from '../../public/SubscribeBox';
import type { CreatedFeedToken } from '../../utils/api-feeds';
import { keys, useT } from '../../utils/i18n';
import type { Calendar } from '../../utils/types';
import { CreatedLink } from './CreatedLink';
import { CreateLinkForm } from './CreateLinkForm';
import { TokenList } from './TokenList';

/** Subscribe to a calendar. A public calendar's feed comes first (the anonymous path of the
 *  public pages); every calendar the caller may view can have private links: one that serves
 *  what the caller may see, and stops with their access.
 *
 *  A new link is held in this component's state only while it is on screen: closing the dialog
 *  clears it, and it is never written to the URL, storage, a toast or a log. */
export function SubscribeDialog({
  calendar,
  canManage,
  contentLocales,
  publicPrefix,
  onGone,
}: {
  calendar: Calendar;
  canManage: boolean;
  contentLocales: string[];
  publicPrefix: string;
  onGone?: () => void;
}) {
  const { t } = useT();
  const copy = keys.events.feeds;
  const [open, setOpen] = useState(false);
  const [created, setCreated] = useState<CreatedFeedToken | null>(null);
  const [tab, setTab] = useState<'mine' | 'everyone'>('mine');
  const state = useFeedTokens(calendar.id, open, canManage, onGone);

  const shown = tab === 'everyone' && state.everyone ? state.everyone : state.mine;
  const change = (next: boolean) => {
    setOpen(next);
    if (!next) {
      setCreated(null); // the link is not kept past the dialog, however it was closed
      setTab('mine');
    }
  };
  return (
    <Dialog open={open} onOpenChange={change}>
      <DialogTrigger asChild>
        <Button
          type="button"
          variant="outline"
          data-testid="events-subscribe"
          aria-label={t(copy.button_for, { name: calendar.name })}
        >
          {t(copy.button)}
        </Button>
      </DialogTrigger>
      <DialogContent
        className="max-h-[calc(100dvh-2rem)] overflow-y-auto"
        showCloseButton={false}
        data-testid="events-subscribe-dialog"
      >
        <DialogHeader>
          <DialogTitle>{t(copy.title)}</DialogTitle>
          <DialogDescription>{t(copy.description)}</DialogDescription>
        </DialogHeader>

        {calendar.visibility === 'public' && (
          <SubscribeBox feedUrl={`${publicPrefix}/c/${calendar.slug}.ics`} />
        )}

        <section className="space-y-2" aria-label={t(copy.private_title)}>
          <h3 className="text-sm font-medium">{t(copy.private_title)}</h3>
          <p className="text-sm text-muted-foreground">{t(copy.private_hint)}</p>
          {created ? (
            <CreatedLink link={created} onDone={() => setCreated(null)} />
          ) : (
            <CreateLinkForm
              locales={contentLocales}
              onCreate={async (input) => {
                const link = await state.create(input);
                if (link) setCreated(link);
              }}
            />
          )}
        </section>

        <section className="space-y-2" aria-label={t(copy.mine)}>
          {canManage && (
            <fieldset className="flex gap-2" aria-label={t(copy.tabs)}>
              {(['mine', 'everyone'] as const).map((name) => (
                <Button
                  key={name}
                  type="button"
                  size="sm"
                  variant={tab === name ? 'default' : 'outline'}
                  aria-pressed={tab === name}
                  onClick={() => setTab(name)}
                >
                  {t(name === 'mine' ? copy.mine : copy.everyone)}
                </Button>
              ))}
            </fieldset>
          )}
          {!canManage && <h3 className="text-sm font-medium">{t(copy.mine)}</h3>}
          {state.error && (
            <p className="text-sm text-destructive" role="alert">
              {state.error}
            </p>
          )}
          {state.loading && state.mine.length === 0 ? (
            <p role="status">{t(keys.events.common.loading)}</p>
          ) : (
            <TokenList
              tokens={shown}
              everyone={tab === 'everyone'}
              onRevoke={async (token) => {
                if (await state.revoke(token)) toast(t(copy.revoked));
              }}
            />
          )}
        </section>

        <Button type="button" variant="outline" onClick={() => change(false)}>
          {t(keys.events.common.close)}
        </Button>
      </DialogContent>
    </Dialog>
  );
}
