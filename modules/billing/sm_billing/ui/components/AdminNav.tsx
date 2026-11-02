import { Link } from '@inertiajs/react';
import { cn } from '@simple-module-py/ui/lib/utils';
import { keys, useT } from '../utils/i18n';

const TABS = [
  {
    key: 'subscriptions',
    label: keys.billing.nav.subscriptions,
    href: '/admin/billing/subscriptions',
  },
  { key: 'usage', label: keys.billing.nav.usage, href: '/admin/billing/usage' },
  { key: 'plans', label: keys.billing.nav.plans, href: '/admin/billing/plans' },
  { key: 'connection', label: keys.billing.nav.connection, href: '/admin/billing/connection' },
] as const;

export type AdminTab = (typeof TABS)[number]['key'];

/**
 * The billing admin screens, as tabs. Toasts need no outlet here:
 * ``AdminLayout`` mounts the ``<Toaster/>`` itself since ui 0.0.36, and a
 * second one would show every toast twice.
 */
export function AdminNav({ active }: { active: AdminTab }) {
  const { t } = useT();
  return (
    <nav aria-label={t(keys.billing.nav.aria_label)} className="mb-4 flex flex-wrap gap-1 border-b">
      {TABS.map((tab) => (
        <Link
          key={tab.key}
          href={tab.href}
          aria-current={tab.key === active ? 'page' : undefined}
          className={cn(
            '-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors max-lg:min-h-11',
            tab.key === active
              ? 'border-primary text-foreground'
              : 'border-transparent text-muted-foreground hover:text-foreground',
          )}
        >
          {t(tab.label)}
        </Link>
      ))}
    </nav>
  );
}
