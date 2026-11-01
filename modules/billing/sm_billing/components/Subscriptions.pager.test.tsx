// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

(globalThis as unknown as { React: unknown }).React = React;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const get = vi.fn();
vi.mock('@inertiajs/react', () => ({ router: { get: (...args: unknown[]) => get(...args) } }));

const { SubscriptionsPager, subscriptionsQuery, visitSubscriptions } = await import(
  './SubscriptionsPager'
);

describe('SubscriptionsPager', () => {
  let root: Root | undefined;
  let host: HTMLDivElement | undefined;

  afterEach(() => {
    act(() => root?.unmount());
    host?.remove();
    get.mockClear();
  });

  async function mount(total: number, page = 1) {
    host = document.createElement('div');
    document.body.append(host);
    root = createRoot(host);
    await act(async () => {
      root?.render(
        <SubscriptionsPager
          filters={{ status: 'active', q: 'acme' }}
          page={page}
          perPage={50}
          total={total}
        />,
      );
    });
  }

  // No catalogue is loaded here, so a label reads as its key.
  const button = (name: 'previous' | 'next') =>
    [...document.querySelectorAll('button')].find((b) => b.textContent === `ui.pagination.${name}`);

  it('is hidden for one page', async () => {
    await mount(50);
    expect(document.body.textContent).toBe('');
  });

  it('is shown for two pages', async () => {
    await mount(51);
    expect(document.body.textContent).toContain('ui.pagination.showing');
    expect(button('previous')?.disabled).toBe(true);
    expect(button('next')?.disabled).toBe(false);
  });

  it('goes to page 2 keeping the status and search', async () => {
    await mount(51);
    await act(async () => button('next')?.click());
    expect(get).toHaveBeenCalledWith(
      '/admin/billing/subscriptions',
      { status: 'active', q: 'acme', page: '2' },
      { preserveScroll: true },
    );
  });

  it('goes back to page 1 without a page parameter', async () => {
    await mount(51, 2);
    await act(async () => button('previous')?.click());
    expect(get.mock.calls[0]?.[1]).toEqual({ status: 'active', q: 'acme' });
  });
});

describe('subscriptionsQuery', () => {
  it('leaves empty filters and page 1 out', () => {
    expect(subscriptionsQuery({ status: '', q: '' })).toEqual({});
    expect(subscriptionsQuery({ status: 'past_due', q: '' }, 3)).toEqual({
      status: 'past_due',
      page: '3',
    });
  });

  it('a filter change visits without a page', () => {
    visitSubscriptions({ status: 'trialing', q: 'x' });
    expect(get.mock.calls.at(-1)?.[1]).toEqual({ status: 'trialing', q: 'x' });
  });
});
