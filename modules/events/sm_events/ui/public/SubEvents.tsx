import { keys, useT } from '../utils/i18n';
import type { PublicListItem } from './types';
import { ItemRow } from './UpcomingList';

export function SubEvents({ items, locale }: { items: PublicListItem[]; locale: string }) {
  const { t } = useT();
  if (items.length === 0) return null;
  return (
    <section aria-labelledby="sub-events-title">
      <h2 id="sub-events-title" className="text-lg font-semibold">
        {t(keys.events.public.event.sub_events)}
      </h2>
      <ul className="divide-y">
        {items.map((item) => (
          <ItemRow key={item.key} item={item} locale={locale} />
        ))}
      </ul>
    </section>
  );
}
