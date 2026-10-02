/** The pure pieces of an article's status: the date-input shape a row edits
 *  in, and the one-line status the list and the article screen each show.
 *
 * Split out of `ArticleRow` when the copy moved into the locale catalogue —
 * that file was already close to the size cap, and these are the only parts of
 * it that read as well on their own as they did inline.
 */

import { type ArticleRead, relativeDay } from '../utils/api';
import { keys, type Translate } from '../utils/i18n';

/** `2026-02-01T00:00:00` -> `2026-02-01`, which is what <input type=date> wants. */
export function toDateInput(iso: string | null): string {
  return iso ? iso.slice(0, 10) : '';
}

/** The article screen's own status, which reads as a header rather than as a
 *  list row.
 *
 * Three statuses, three readings — `submitted_for_review` used to fall
 * through the `!isPublished` branch and read as published, which is wrong in
 * a way that specifically hurts the reviewer: whoever is looking at a
 * just-submitted article needs to know it is *not* live yet.
 */
export function editorStatus(status: ArticleRead['status'], dated: string, t: Translate): string {
  const copy = keys.news.editor;
  if (status === 'published') {
    return dated ? t(copy.status_published_dated, { date: dated }) : t(copy.status_published);
  }
  if (status === 'submitted_for_review') {
    return dated ? t(copy.status_pending_dated, { date: dated }) : t(copy.status_pending);
  }
  return dated ? t(copy.status_draft_dated, { date: dated }) : t(copy.status_draft_undated);
}

/** The one-line status the card carries under its metadata.
 *
 * `published_at` is the editorial display date, not a schedule — the field
 * that actually drives auto-publish is `publish_at`, set from ScheduleCard
 * and not read anywhere in this list. A future `published_at` used to read
 * as "publishes {date}", which promised something this row cannot keep: an
 * editor could set a future display date, see "publishes …" and believe the
 * article will go live on its own when nothing here does that.
 */
export function statusLine(article: ArticleRead, t: Translate): string {
  const when = article.published_at;
  const row = keys.news.row;

  if (article.status === 'published') {
    return when
      ? t(row.status_published_dated, { when: relativeDay(when, t) })
      : t(row.status_published_undated);
  }
  if (article.status === 'submitted_for_review') return t(row.status_pending);
  return when
    ? t(row.status_draft_dated, { when: relativeDay(when, t) })
    : t(row.status_draft_undated);
}
