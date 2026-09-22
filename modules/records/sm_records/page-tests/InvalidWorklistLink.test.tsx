// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { mount } from '../test-dom';
import type { TypeRead } from '../utils/types';

vi.mock('@inertiajs/react', () => ({
  Head: () => null,
  Link: ({ children, ...rest }: { children?: unknown; [key: string]: unknown }) => (
    // biome-ignore lint/suspicious/noExplicitAny: a thin passthrough stand-in for Inertia's Link
    <a {...(rest as any)}>{children as React.ReactNode}</a>
  ),
}));

const Types = (await import('../pages/Types')).default;

function type(overrides: Partial<TypeRead> = {}): TypeRead {
  return {
    key: 'order',
    label: 'Order',
    label_plural: 'Orders',
    description: null,
    icon: null,
    show_in_menu: false,
    collection: null,
    record_count: 12,
    trashed_record_count: 0,
    invalid_record_count: 0,
    is_public: false,
    ...overrides,
  } as unknown as TypeRead;
}

function setNarrow(matches: boolean): void {
  window.matchMedia = ((query: string) => ({
    matches,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  })) as unknown as typeof window.matchMedia;
}

const LINK = '[data-testid="records-type-invalid-count"]';

describe('R7c: the hub row counts the marked records and links to them', () => {
  afterEach(() => {
    // @ts-expect-error — undo the stub between tests
    window.matchMedia = undefined;
  });

  for (const [layout, narrow] of [
    ['the table', false],
    ['the phone cards', true],
  ] as const) {
    describe(layout, () => {
      beforeEach(() => setNarrow(narrow));

      it('links the count to the list filtered by the same flag', async () => {
        const view = await mount(<Types types={[type({ invalid_record_count: 3 })]} />);
        const link = view.find<HTMLAnchorElement>(LINK);
        // The count itself is interpolated by `@simple-module-py/i18n`,
        // which is not configured under vitest — the assertion is that the
        // link is there, says what it is, and points at the right list.
        expect(link?.textContent).toContain('invalid');
        // The count is only useful one click from the records it counts.
        expect(link?.getAttribute('href')).toBe('/admin/records/order?filter=invalid:eq:true');
        await view.unmount();
      });

      it('says nothing when the type has none', async () => {
        const view = await mount(<Types types={[type()]} />);
        expect(view.find(LINK)).toBeNull();
        await view.unmount();
      });
    });
  }
});
