// @vitest-environment happy-dom
import { configureI18n } from '@simple-module-py/i18n';
import { describe, expect, it } from 'vitest';

import catalog from '../locales/en.json';
import { mount } from '../test-dom';
import { TenantBadge } from './TenantBadge';

/** `en.json` flattened the way the host ships it: `records.<path>`. */
function flatten(node: Record<string, unknown>, prefix: string): Record<string, string> {
  return Object.fromEntries(
    Object.entries(node).flatMap(([key, value]) =>
      typeof value === 'string'
        ? [[`${prefix}.${key}`, value]]
        : Object.entries(flatten(value as Record<string, unknown>, `${prefix}.${key}`)),
    ),
  );
}

/**
 * The badge used to call `t('common.tenant_badge')` without the `records.`
 * namespace, so the key never resolved and every locale saw the English
 * `defaultValue`. A pseudo-locale that brackets each catalog entry tells the
 * two apart: only a key that really resolves against `en.json` renders
 * bracketed, and i18next's own `{tenant}` interpolation still runs.
 */
describe('TenantBadge', () => {
  it('renders the catalog entry, not the defaultValue', async () => {
    const messages = flatten(catalog, 'records');
    expect(messages['records.common.tenant_badge']).toBe('Tenant: {tenant}');
    configureI18n({
      locale: 'xx',
      messages: Object.fromEntries(Object.entries(messages).map(([k, v]) => [k, `[${v}]`])),
    });
    const view = await mount(<TenantBadge tenant="acme" tenancyMode="multi" />);
    expect(view.find('[data-testid="records-tenant-badge"]')?.textContent).toBe('[Tenant: acme]');
    await view.unmount();
  });
});
