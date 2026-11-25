// @vitest-environment happy-dom
import * as React from 'react';
import { act, useEffect } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ArticleFilters } from '../components/ArticleFilters';
import { trashArticle } from '../utils/api';
import { useArticleList } from './useArticleList';

(globalThis as unknown as { React: unknown }).React = React;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let host: HTMLDivElement;
let list: ReturnType<typeof useArticleList>;
let removed: boolean;
let staleRow: boolean;
let categoriesFail: boolean;
let urls: URL[];

function Harness() {
  const current = useArticleList();
  list = current;
  const { load } = current;
  useEffect(() => {
    void load();
  }, [load]);
  return (
    <ArticleFilters
      {...list.filters}
      counts={list.counts}
      categories={list.categories}
      locales={['en', 'de']}
      onChange={list.setFilters}
    />
  );
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

beforeEach(() => {
  removed = false;
  staleRow = false;
  categoriesFail = false;
  urls = [];
  window.history.replaceState(null, '', '/admin/news/?category=Politics');
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = new URL(input, 'http://localhost');
      urls.push(url);
      if (init?.method === 'POST') {
        removed = true;
        return staleRow
          ? json({ detail: 'Article not found.' }, 404)
          : new Response(null, { status: 204 });
      }
      if (url.pathname.endsWith('/categories')) {
        if (categoriesFail) return json({ detail: 'Try later' }, 503);
        return json({ items: removed ? [] : [{ category: 'Politics', count: 1 }] });
      }
      const total = url.searchParams.has('category') ? (removed ? 0 : 1) : 18;
      return json({
        items: total ? [{ id: 7, title: 'Visible' }] : [],
        total,
        counts: { all: total, published: total, draft: 0, undated: 0 },
      });
    }),
  );
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  window.history.replaceState(null, '', '/');
});

it('clears a category removed by refetch and loads all articles', async () => {
  await act(async () => root.render(<Harness />));
  expect(host.querySelector('select')?.value).toBe('Politics');
  await act(async () => {
    await list.runRow(7, () => trashArticle(7));
  });
  expect(list.filters.category).toBe('');
  expect(window.location.search).toBe('');
  expect(list.total).toBe(18);
  expect(list.counts.all).toBe(18);
  expect(
    urls
      .filter((u) => u.pathname.endsWith('/articles'))
      .at(-1)
      ?.searchParams.has('category'),
  ).toBe(false);
});

it('keeps the selected category when fetching options fails', async () => {
  await act(async () => root.render(<Harness />));
  categoriesFail = true;
  await act(async () => {
    await list.load();
  });
  expect(list.filters.category).toBe('Politics');
  expect(host.querySelector('select')?.value).toBe('Politics');
});

it('refreshes a stale list row and counts when trash answers 404', async () => {
  await act(async () => root.render(<Harness />));
  staleRow = true;
  await act(async () => {
    await list.runRow(7, () => trashArticle(7));
  });
  expect(list.filters.category).toBe('');
  expect(list.total).toBe(18);
  expect(list.busyId).toBeNull();
});

it('clears unavailable status and language options before refetching', async () => {
  window.history.replaceState(null, '', '/admin/news/?status=obsolete&locale=fr');
  await act(async () => root.render(<Harness />));
  expect(list.filters.status).toBe('');
  expect(list.filters.locale).toBe('');
  const last = urls.filter((u) => u.pathname.endsWith('/articles')).at(-1);
  expect(last?.searchParams.has('status')).toBe(false);
  expect(last?.searchParams.has('locale')).toBe(false);
});

it('keeps a valid status even when its count is zero', async () => {
  window.history.replaceState(null, '', '/admin/news/?status=draft');
  await act(async () => root.render(<Harness />));
  expect(list.filters.status).toBe('draft');
  expect(host.querySelector('[aria-pressed="true"]')?.textContent).toContain('Draft');
});
