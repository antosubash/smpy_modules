/** The hits of a card search: a title and a line of detail per source, one button each. */

import { keys, useT } from '../../utils/i18n';
import type { CardHit } from '../../utils/types';

const copy = keys.newsletter.editor.card;

function HitDetail({ hit }: { hit: CardHit }) {
  const { t } = useT();
  if (hit.kind !== 'event') {
    return hit.excerpt ? (
      <span className="line-clamp-2 block text-xs text-muted-foreground">{hit.excerpt}</span>
    ) : null;
  }
  return (
    <span className="block text-xs text-muted-foreground">
      {hit.cancelled && (
        <span className="mr-1 font-medium text-destructive">
          {t(keys.newsletter.email.cancelled)}
        </span>
      )}
      {hit.when}
    </span>
  );
}

export function CardHits(props: {
  hits: CardHit[] | null;
  busy: boolean;
  onPick: (hit: CardHit) => void;
}) {
  const { t } = useT();
  const { hits, busy, onPick } = props;
  if (hits === null) return <p className="text-xs text-muted-foreground">{t(copy.searching)}</p>;
  if (hits.length === 0) {
    return <p className="text-xs text-muted-foreground">{t(copy.no_results)}</p>;
  }
  return (
    <ul className="max-h-64 space-y-1 overflow-y-auto">
      {hits.map((hit) => (
        <li key={`${hit.kind}-${hit.source_id}`}>
          <button
            type="button"
            disabled={busy}
            className="w-full rounded border p-2 text-left text-sm hover:bg-muted disabled:opacity-50"
            onClick={() => onPick(hit)}
          >
            <span className="block font-medium">{hit.title}</span>
            <HitDetail hit={hit} />
          </button>
        </li>
      ))}
    </ul>
  );
}
