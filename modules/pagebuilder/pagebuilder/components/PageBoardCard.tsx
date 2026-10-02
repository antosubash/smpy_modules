import { router } from '@inertiajs/react';
import { Button } from '@simple-module-py/ui/components/ui/button';

import type { PageRead } from '../utils/api';
import { keys, translate, useT } from '../utils/i18n';
import { publicPath } from '../utils/locale';
import { ConfirmDialog } from './ConfirmDialog';

/** Where pages serve publicly. Mirrors `PagebuilderSettings.public_route_prefix`. */
const PUBLIC_PREFIX = '/p';

/** "1 Sep, 09:00" — when a scheduled draft flips itself. */
function whenLabel(iso: string | null | undefined): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/** "in 21d" / "2d ago", from a full timestamp.
 *
 *  Through `translate` rather than a hook: this is a plain function the card
 *  calls while rendering, so it reads the language in force at that moment
 *  without every caller threading `t` in. */
function relative(iso: string | null | undefined): string {
  if (!iso) return '';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const days = Math.round((then - Date.now()) / 86_400_000);
  if (days === 0) return translate(keys.pagebuilder.card.today);
  return days > 0
    ? translate(keys.pagebuilder.card.in_days, { count: days })
    : translate(keys.pagebuilder.card.days_ago, { count: -days });
}

interface Props {
  page: PageRead;
  stage: string;
  /** The language that serves unprefixed, so a card shows the address its own
   *  page actually answers on rather than the default language's. */
  defaultLocale: string;
  onDelete: (page: PageRead) => Promise<unknown>;
  onPublish: (page: PageRead) => Promise<unknown>;
  onUnpublish: (page: PageRead) => Promise<unknown>;
}

/** One page on the board. The line under the title says the thing that stage
 *  actually cares about — when a scheduled page fires, when a draft was last
 *  touched, whether a published page has unpublished edits waiting. */
export function PageBoardCard({
  page,
  stage,
  defaultLocale,
  onDelete,
  onPublish,
  onUnpublish,
}: Props) {
  const { t } = useT();
  const scheduled = stage === 'scheduled';
  const published = page.status === 'published';
  const address = publicPath(PUBLIC_PREFIX, page.slug, page.locale, defaultLocale);

  const meta = scheduled
    ? t(keys.pagebuilder.card.publishes, {
        when: whenLabel(page.publish_at),
        relative: relative(page.publish_at),
      })
    : `${address}${page.updated_at ? ` · ${relative(page.updated_at)}` : ''}`;

  return (
    <li
      data-testid="board-card"
      data-slug={page.slug}
      className="rounded-md border bg-card p-3 shadow-sm"
    >
      <button
        type="button"
        onClick={() => router.visit(`/pagebuilder/${page.id}/edit`)}
        className="block w-full text-left font-medium hover:underline"
      >
        {page.title || t(keys.pagebuilder.card.untitled)}
      </button>
      <p className="mt-0.5 truncate text-xs text-muted-foreground">{meta}</p>

      <div className="mt-2 flex flex-wrap gap-1">
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => router.visit(`/pagebuilder/${page.id}/edit`)}
        >
          {t(keys.pagebuilder.card.edit)}
        </Button>

        {!published && (
          <Button type="button" size="sm" onClick={() => void onPublish(page).catch(() => {})}>
            {scheduled ? t(keys.pagebuilder.card.publish_now) : t(keys.pagebuilder.card.publish)}
          </Button>
        )}

        {published && (
          <Button type="button" size="sm" variant="outline" asChild>
            <a href={address} target="_blank" rel="noopener noreferrer">
              {t(keys.pagebuilder.card.view)}
            </a>
          </Button>
        )}

        {published && (
          <ConfirmDialog
            // Medium: it takes effect publicly and at once, but nothing is
            // lost — which is the distinction the copy has to carry, or people
            // read "unpublish" as "delete".
            level="medium"
            title={t(keys.pagebuilder.card.unpublish_title, { title: page.title })}
            description={
              // The address is a <code> span inside the sentence, so the two
              // halves are separate keys rather than one with a placeholder.
              <>
                <code>/p/{page.slug}</code> {t(keys.pagebuilder.card.unpublish_description)}
              </>
            }
            confirmLabel={t(keys.pagebuilder.card.unpublish)}
            onConfirm={() => onUnpublish(page)}
            trigger={
              <Button type="button" size="sm" variant="ghost">
                {t(keys.pagebuilder.card.unpublish)}
              </Button>
            }
          />
        )}

        <ConfirmDialog
          // Deleting a published page is the design's high blast radius: it is
          // live, it is linked, and the URL starts answering 404 immediately.
          // The typed slug is what separates it from deleting a draft nobody
          // has ever seen.
          level={published ? 'high' : 'low'}
          confirmPhrase={published ? page.slug : undefined}
          title={t(keys.pagebuilder.row.delete_title, { title: page.title })}
          description={
            published ? (
              <>
                {t(keys.pagebuilder.row.delete_published_before)} <code>/p/{page.slug}</code>{' '}
                {t(keys.pagebuilder.row.delete_published_after)}
              </>
            ) : (
              t(keys.pagebuilder.row.delete_draft)
            )
          }
          confirmLabel={t(keys.pagebuilder.card.delete)}
          onConfirm={() => onDelete(page)}
          trigger={
            <Button type="button" size="sm" variant="ghost" className="text-destructive">
              {t(keys.pagebuilder.card.delete)}
            </Button>
          }
        />
      </div>
    </li>
  );
}
