import { Button } from '@simple-module-py/ui/components/ui/button';
import type { FeedToken } from '../../utils/api-feeds';
import { formatDay } from '../../utils/datetime';
import { keys, useT } from '../../utils/i18n';
import { Name, withName } from '../../utils/isolate';
import { ownLanguageName } from '../../utils/language';
import { ConfirmDialog } from '../ConfirmDialog';

/** Links as listed by the server: label, language, created, last used (coarse, to the hour)
 *  and Revoke. Never a link: nothing here could show one. */
export function TokenList({
  tokens,
  everyone,
  onRevoke,
}: {
  tokens: FeedToken[];
  /** Show whose each link is (the "Everyone's links" tab). */
  everyone: boolean;
  onRevoke: (token: FeedToken) => Promise<unknown>;
}) {
  const { t, locale } = useT();
  const copy = keys.events.feeds;
  const day = (iso: string) => formatDay(iso, locale);
  if (tokens.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {t(everyone ? copy.none_everyone : copy.none)}
      </p>
    );
  }
  return (
    <ul className="divide-y rounded-md border" data-testid="events-feed-list">
      {tokens.map((token) => (
        <li
          key={token.id}
          className="flex items-center justify-between gap-2 px-3 py-2 text-sm"
          data-testid="events-feed-row"
        >
          <span className="min-w-0 break-words">
            <Name>{token.label}</Name> · {ownLanguageName(token.locale)} · {t(copy.created)}{' '}
            {day(token.created_at)} · {t(copy.last_used)}{' '}
            {token.last_used_at ? day(token.last_used_at) : t(copy.never_used)}
            {everyone && (
              <> · {token.user_name ? <Name>{token.user_name}</Name> : t(copy.unknown_user)}</>
            )}
          </span>
          <ConfirmDialog
            trigger={
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={t(copy.revoke_for, { name: token.label })}
              >
                {t(copy.revoke)}
              </Button>
            }
            title={withName(t, copy.revoke_title, token.label)}
            description={t(copy.revoke_description)}
            confirmLabel={t(copy.revoke)}
            onConfirm={() => onRevoke(token)}
          />
        </li>
      ))}
    </ul>
  );
}
