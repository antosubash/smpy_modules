import { Head } from '@inertiajs/react';
import { keys, useT } from '../utils/i18n';

export interface ArchiveHeadProps {
  heading: string;
  query?: string;
}

/** Archive titles and the crawler policy for query results. */
export function ArchiveHead({ heading, query = '' }: ArchiveHeadProps) {
  const { t } = useT();
  const copy = keys.news.public;
  return (
    <Head title={query ? t(copy.title_with_query, { query, heading }) : heading}>
      {/* Results pages stay out of the index: the input space is unbounded,
        so one indexed `?q=` link invites a crawler to enumerate query
        strings forever, and every result page is a rearrangement of
        articles already indexed at their own addresses. `follow`, though —
        the links out of it are the real documents. The server writes the
        same tag into the head for the crawler that never runs this script;
        see `endpoints/public/_head.py`. */}
      {query && <meta name="robots" content="noindex,follow" />}
    </Head>
  );
}
