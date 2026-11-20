/** What the public site adds under an external entry: where it comes from and the link to the
 *  source, as plain text and one vetted anchor. */
import type { PublicDetailProps } from '../../extensions/types';
import { keys, useT } from '../../utils/i18n';
import { isWebUrl } from './ExternalDetail';

export default function ExternalPublicDetail({ occurrence }: PublicDetailProps) {
  const { t } = useT();
  const copy = keys.events.subscriptions;
  if (!occurrence) return null;
  return (
    <div className="space-y-1 text-sm" data-testid="external-public-detail">
      <p className="text-muted-foreground">
        {t(copy.from_label, { label: occurrence.origin_label ?? '' })}
      </p>
      {occurrence.location ? (
        <p data-testid="external-public-location">{occurrence.location}</p>
      ) : null}
      {isWebUrl(occurrence.url) ? (
        <a
          href={occurrence.url}
          target="_blank"
          rel="noopener noreferrer nofollow"
          className="underline"
        >
          {t(copy.open_source_link)}
        </a>
      ) : null}
    </div>
  );
}
