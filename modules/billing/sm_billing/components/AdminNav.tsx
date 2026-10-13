import { Link } from '@inertiajs/react';
import { Toaster } from '@simple-module-py/ui/components/ui/sonner';
import { cn } from '@simple-module-py/ui/lib/utils';
import { keys, useT } from '../utils/i18n';

const TABS = [
  {
    key: 'subscriptions',
    label: keys.billing.nav.subscriptions,
    href: '/admin/billing/subscriptions',
  },
  { key: 'plans', label: keys.billing.nav.plans, href: '/admin/billing/plans' },
  { key: 'connection', label: keys.billing.nav.connection, href: '/admin/billing/connection' },
] as const;

export type AdminTab = (typeof TABS)[number]['key'];

/**
 * The three billing admin screens, as tabs — and their toast outlet.
 *
 * ``AdminLayout`` (unlike ``AuthenticatedLayout``) mounts no ``<Toaster/>``,
 * so without this every save confirmation and every API error on these
 * screens would be raised into nothing. Every billing admin page renders this
 * nav, which makes it the one place that guarantees the outlet exists.
 */
export function AdminNav({ active }: { active: AdminTab }) {
  const { t } = useT();
  return (
    <>
      <nav aria-label={t(keys.billing.nav.aria_label)} className="mb-4 flex gap-1 border-b">
        {TABS.map((tab) => (
          <Link
            key={tab.key}
            href={tab.href}
            aria-current={tab.key === active ? 'page' : undefined}
            className={cn(
              '-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors max-lg:min-h-11',
              tab.key === active
                ? 'border-primary text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground',
            )}
          >
            {t(tab.label)}
          </Link>
        ))}
      </nav>
      <Toaster richColors position="top-right" />
    </>
  );
}
