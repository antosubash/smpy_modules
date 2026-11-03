/** "As it appears" — what the page looks like in a result list and a social card. */

import { keys, useT } from '../../utils/i18n';

interface Props {
  /** Site origin, e.g. `acmelab.org`. Falls back to the browser's. */
  host: string;
  slug: string;
  publicPrefix: string;
  metaTitle: string;
  /** Used when the meta title is blank, which is the common case. */
  pageTitle: string;
  metaDescription: string;
  socialImage: string;
}

/** Google truncates around here. Approximate on purpose — the real limit is
 *  pixel width, not characters, so a hard cut-off would be its own kind of
 *  lie. The counters warn; they do not block. */
const TITLE_LIMIT = 60;
const DESCRIPTION_LIMIT = 155;

function truncate(value: string, limit: number): string {
  return value.length > limit ? `${value.slice(0, limit - 1).trimEnd()}…` : value;
}

/** A live preview of the two places this metadata is actually read.
 *
 * It exists because the fields above it are written blind otherwise: a meta
 * description is a sentence nobody sees in context until it is already on
 * Google, and the length limits only mean something when you can watch the
 * ellipsis land.
 */
export function SeoPreview({
  host,
  slug,
  publicPrefix,
  metaTitle,
  pageTitle,
  metaDescription,
  socialImage,
}: Props) {
  const { t } = useT();
  const title = metaTitle.trim() || pageTitle.trim() || t(keys.pagebuilder.seo.untitled_page);
  const path = `${publicPrefix.replace(/^\//, '')} › ${slug || t(keys.pagebuilder.seo.untitled_slug)}`;
  const description = metaDescription.trim();

  return (
    <div className="grid gap-3" data-testid="seo-preview">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {t(keys.pagebuilder.seo.as_it_appears)}
      </p>

      {/* Search result */}
      <div className="rounded-md border bg-card p-3">
        <p className="truncate text-xs text-muted-foreground">
          {host} › {path}
        </p>
        <p className="mt-0.5 text-base text-[#1a0dab] dark:text-[#8ab4f8]">
          {truncate(title, TITLE_LIMIT)}
        </p>
        <p className="mt-0.5 text-sm text-muted-foreground">
          {description ? (
            truncate(description, DESCRIPTION_LIMIT)
          ) : (
            <span className="italic">{t(keys.pagebuilder.seo.no_description)}</span>
          )}
        </p>
      </div>

      {/* Social card */}
      <div className="overflow-hidden rounded-md border bg-card">
        {socialImage ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={socialImage}
            alt=""
            className="aspect-[1200/630] w-full bg-muted object-cover"
          />
        ) : (
          <div className="flex aspect-[1200/630] w-full items-center justify-center bg-muted text-xs text-muted-foreground">
            {t(keys.pagebuilder.seo.no_social_image)}
          </div>
        )}
        <div className="px-3 py-2">
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{host}</p>
          <p className="truncate text-sm font-medium">{title}</p>
        </div>
      </div>
    </div>
  );
}

export { DESCRIPTION_LIMIT, TITLE_LIMIT };
