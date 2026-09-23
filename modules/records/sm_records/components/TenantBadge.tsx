import { useT } from '@simple-module-py/i18n';
import { Badge } from '@simple-module-py/ui/components/ui/badge';

import type { TenancyMode } from '../utils/types';

/**
 * "Which tenant am I working in" — read-only, shown next to a records admin
 * screen's title actions (tenancy design §I/§J: `tenant` is a read-only view
 * prop precisely so the UI can say this). Renders nothing at all outside
 * `'multi'` mode: a single-tenant host has exactly one tenant (`default`),
 * and naming it on every screen would be noise nobody asked for — the design
 * is explicit that single mode "shows nothing new".
 *
 * `tenancyMode`/`tenant` are optional here the same way `public_route_prefix`
 * is elsewhere in this module: `tenancy.view_props` sends both on every
 * render, but an absent prop (an older fixture, a screen this phase didn't
 * reach) degrades to "no badge" rather than a crash.
 */
export function TenantBadge({
  tenant,
  tenancyMode,
}: {
  tenant?: string;
  tenancyMode?: TenancyMode;
}) {
  const { t } = useT();
  if (tenancyMode !== 'multi' || !tenant) return null;
  return (
    <Badge variant="secondary" data-testid="records-tenant-badge">
      {t('common.tenant_badge', { tenant, defaultValue: 'Tenant: {tenant}' })}
    </Badge>
  );
}
