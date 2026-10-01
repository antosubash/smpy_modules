import { Link } from '@inertiajs/react';
import { cn } from '@simple-module-py/ui/lib/utils';

const TABS = [
  { key: 'subscriptions', label: 'Subscriptions', href: '/admin/billing/subscriptions' },
  { key: 'plans', label: 'Plans', href: '/admin/billing/plans' },
  { key: 'connection', label: 'Stripe connection', href: '/admin/billing/connection' },
] as const;

export type AdminTab = (typeof TABS)[number]['key'];

/** The three billing admin screens, as tabs. */
export function AdminNav({ active }: { active: AdminTab }) {
  return (
    <nav aria-label="Billing administration" className="mb-4 flex gap-1 border-b">
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
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}
