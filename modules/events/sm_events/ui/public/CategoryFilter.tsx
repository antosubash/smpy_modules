import { keys, useT } from '../utils/i18n';
import type { PublicCategory } from './types';

/** Category links, not a script-driven select: each is a real address (`?category=slug`), so a
 *  filter works without JavaScript and a crawler can follow it. */
export function CategoryFilter({
  categories,
  active,
  base,
}: {
  categories: PublicCategory[];
  active: string | null;
  /** The page's own path, so the filter stays on the calendar being viewed. */
  base: string;
}) {
  const { t } = useT();
  if (categories.length === 0) return null;
  const copy = keys.events.public.index.filter;
  return (
    <nav aria-label={t(copy.label)} className="flex flex-wrap items-center gap-2 text-sm">
      <span className="text-muted-foreground">{t(copy.category)}</span>
      <a
        href={base}
        aria-current={active === null ? 'true' : undefined}
        className={active === null ? 'font-semibold' : 'underline'}
      >
        {t(copy.all)}
      </a>
      {categories.map((c) => (
        <a
          key={c.id}
          href={`${base}?category=${encodeURIComponent(c.slug)}`}
          aria-current={active === c.slug ? 'true' : undefined}
          className={active === c.slug ? 'font-semibold' : 'underline'}
        >
          {c.name}
        </a>
      ))}
    </nav>
  );
}
