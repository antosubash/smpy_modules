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

const Types = (await import('./Types')).default;

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
    ...overrides,
  } as unknown as TypeRead;
}

/** Stub `window.matchMedia` for the `useIsNarrow` hook — happy-dom doesn't
 *  implement it, and `useIsNarrow` degrades to "wide" without it, which is
 *  exactly the branch these tests need to override. */
function setNarrow(matches: boolean): void {
  window.matchMedia = ((query: string) => ({
    matches,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  })) as unknown as typeof window.matchMedia;
}

describe('Types — U7: the hub gets the same phone card layout the record list has', () => {
  beforeEach(() => setNarrow(true));
  afterEach(() => {
    // @ts-expect-error — undo the stub between tests
    window.matchMedia = undefined;
  });

  it('renders cards, not a table, below the sm breakpoint, with Edit schema reachable', async () => {
    const view = await mount(<Types types={[type()]} />);
    expect(view.find('table')).toBeNull();
    const card = view.find('[data-testid="records-type-card"]');
    expect(card).not.toBeNull();
    const editSchema = view.find<HTMLAnchorElement>('[data-testid="records-type-edit-schema"]');
    expect(editSchema?.getAttribute('href')).toBe('/admin/records/types/order');
    const typeLink = view.find<HTMLAnchorElement>('[data-testid="records-type-link"]');
    expect(typeLink?.getAttribute('href')).toBe('/admin/records/order');
    await view.unmount();
  });
});

describe('Types — the table is unchanged at desktop widths', () => {
  beforeEach(() => setNarrow(false));
  afterEach(() => {
    // @ts-expect-error — undo the stub between tests
    window.matchMedia = undefined;
  });

  it('renders the table, not cards', async () => {
    const view = await mount(<Types types={[type()]} />);
    expect(view.find('table')).not.toBeNull();
    expect(view.find('[data-testid="records-type-card"]')).toBeNull();
    await view.unmount();
  });
});
