// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { HistoryCard } from '../components/editor/HistoryCard';
import { ReviewCard } from '../components/editor/ReviewCard';
import { ScheduleCard } from '../components/editor/ScheduleCard';
import { SeoCard } from '../components/editor/SeoCard';
import { useArticleEditor } from './useArticleEditor';

(globalThis as unknown as { React: unknown }).React = React;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const FIRST = '2026-01-01T00:00:00Z';
const SECOND = '2026-01-01T00:00:05Z';
const STALE =
  'This article was changed somewhere else. Reload to get the latest version, then make your change again.';
let editor: ReturnType<typeof useArticleEditor>;
let root: Root;
let host: HTMLDivElement;
let version: string;
let reject: string | null;
let status: 'draft' | 'published' | 'submitted_for_review';
let requests: { url: string; method: string; body: Record<string, unknown> }[];

function article() {
  return {
    id: 7,
    title: 'Original',
    slug: 'original',
    category: '',
    excerpt: '',
    cover_image_url: '',
    pinned: false,
    show_in_feed: true,
    author: '',
    locale: 'en',
    translation_group: 'group',
    has_unpublished_changes: false,
    url: '/news/original',
    edit_url: '/admin/news/articles/7/body',
    meta_description: '',
    og_image: '',
    canonical_url: '',
    json_ld: null,
    rejection_note: null,
    publish_at: null,
    unpublish_at: null,
    has_published: false,
    draft_data: {},
    tags: [],
    status,
    updated_at: version,
    published_at: null,
    index_in_search: true,
  };
}
function json(body: unknown, code = 200) {
  return new Response(JSON.stringify(body), {
    status: code,
    headers: { 'content-type': 'application/json' },
  });
}
function Harness() {
  editor = useArticleEditor(7);
  return (
    <>
      <SeoCard articleId={7} onChanged={editor.acceptWrite} />
      <ScheduleCard articleId={7} onChanged={editor.acceptWrite} />
      <HistoryCard articleId={7} onChanged={(updated) => editor.acceptWrite(updated, true)} />
      {editor.article && (
        <ReviewCard article={editor.article} canPublish onChanged={editor.acceptWrite} />
      )}
    </>
  );
}

beforeEach(async () => {
  version = FIRST;
  reject = null;
  status = 'draft';
  requests = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET';
      const body = init?.body ? JSON.parse(String(init.body)) : {};
      requests.push({ url, method, body });
      if (method === 'GET') {
        if (url.includes('/taxonomy/')) return json({ items: [] });
        if (url.endsWith('/revisions'))
          return json([
            {
              id: 1,
              article_id: 7,
              title: 'Restored title',
              event: 'publish',
              note: null,
              created_at: FIRST,
              created_by: 'Editor',
            },
          ]);
        return json(article());
      }
      if (reject === 'metadata' && url.endsWith('/7'))
        return json({ detail: 'Invalid title' }, 422);
      if (reject === 'tags' && url.endsWith('/tags')) return json({ detail: 'Invalid tag' }, 422);
      if (url.endsWith('/tags')) return json([]);
      if (body.expected_updated_at && body.expected_updated_at !== version)
        return json({ detail: STALE }, 409);
      if (url.endsWith('/publish')) status = 'published';
      if (url.endsWith('/unpublish')) status = 'draft';
      if (url.endsWith('/submit')) status = 'submitted_for_review';
      if (url.endsWith('/approve')) status = 'published';
      if (url.endsWith('/reject')) status = 'draft';
      if (url.endsWith('/revisions/1/restore')) {
        version = SECOND;
        return json({ ...article(), title: 'Restored title' });
      }
      version = SECOND;
      return json(article());
    }),
  );
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<Harness />));
  await act(async () => {
    await editor.load();
  });
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
async function click(text: string) {
  const button = Array.from(document.querySelectorAll('button'))
    .filter((b) => b.textContent?.trim() === text)
    .at(-1);
  expect(button, text).toBeDefined();
  await act(async () => button?.click());
}
async function save() {
  await act(async () => editor.patch({ title: 'Unsaved headline' }));
  await act(async () => {
    await editor.save();
  });
}
function lastSave() {
  return requests.filter((r) => r.method === 'PUT' && r.url.endsWith('/7')).at(-1);
}

it.each(['Save search settings', 'Save schedule'])(
  '%s then main Save sends the returned version and keeps unsaved edits',
  async (button) => {
    await act(async () => editor.patch({ title: 'Unsaved headline' }));
    await click(button);
    expect(editor.draft?.title).toBe('Unsaved headline');
    await act(async () => {
      await editor.save();
    });
    expect(lastSave()?.body.expected_updated_at).toBe(SECOND);
    expect(lastSave()?.body.title).toBe('Unsaved headline');
    expect(editor.conflict).toBe(false);
  },
);

it.each(['metadata', 'tags'])(
  'a rejected %s save then Save uses the last successful version',
  async (failure) => {
    reject = failure;
    await save();
    expect(editor.error).toContain('Invalid');
    reject = null;
    await save();
    expect(lastSave()?.body.expected_updated_at).toBe(failure === 'metadata' ? FIRST : SECOND);
    expect(editor.conflict).toBe(false);
    expect(editor.saved).toBe(true);
  },
);

it('publish and unpublish refresh the version without dropping pending inspector edits', async () => {
  await act(async () => editor.patch({ title: 'Pending' }));
  await act(async () => {
    await editor.publish();
  });
  expect(editor.article?.status).toBe('published');
  expect(editor.draft?.title).toBe('Pending');
  expect(editor.dirty).toBe(true);
  await click('Unpublish');
  await click('Unpublish');
  await act(async () => {
    await editor.save();
  });
  expect(lastSave()?.body.expected_updated_at).toBe(SECOND);
  expect(editor.article?.status).toBe('draft');
});

it('a genuine concurrent edit still shows the 409 message and preserves the draft', async () => {
  version = SECOND;
  await save();
  expect(editor.conflict).toBe(true);
  expect(editor.error).toBe(STALE);
  expect(editor.draft?.title).toBe('Unsaved headline');
});

it('revision restore adopts the restored headline and version while keeping other pending fields', async () => {
  await act(async () => editor.patch({ title: 'Pending headline', author: 'Pending author' }));
  await click('Restore this version');
  await click('Restore');
  expect(editor.draft?.title).toBe('Restored title');
  expect(editor.draft?.author).toBe('Pending author');
  await act(async () => {
    await editor.save();
  });
  expect(lastSave()?.body.expected_updated_at).toBe(SECOND);
  expect(lastSave()?.body.title).toBe('Restored title');
});

it.each(['Approve', 'Send back'])('review %s refreshes the main form version', async (action) => {
  await act(async () => editor.patch({ title: 'Pending headline' }));
  await click('Submit for review');
  expect(editor.article?.status).toBe('submitted_for_review');
  // The review cooldown prevents double-clicks from triggering a second transition.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 850));
  });
  await click(action);
  if (action === 'Send back') await click(action);
  expect(editor.article?.status).toBe(action === 'Approve' ? 'published' : 'draft');
  expect(editor.draft?.title).toBe('Pending headline');
  await act(async () => {
    await editor.save();
  });
  expect(lastSave()?.body.expected_updated_at).toBe(SECOND);
});

it.each([
  [FIRST, SECOND, 'Newer headline', 'Pending headline'],
  [FIRST, SECOND, 'Original', 'Original'],
  ['2026-01-01T00:00:00.000001Z', '2026-01-01T00:00:00.000002Z', 'Newer', 'Pending headline'],
])(
  'delayed restore %s after %s with headline %s keeps %s',
  async (older, newer, title, expected) => {
    await act(async () => editor.patch({ title: 'Pending headline' }));
    await act(async () => editor.acceptWrite({ ...article(), updated_at: newer, title }));
    await act(async () => editor.acceptWrite({ ...article(), updated_at: older }, true));
    expect(editor.article?.updated_at).toBe(newer);
    expect(editor.draft?.title).toBe(expected);
  },
);

it('tags finishing after a side-card save do not roll the metadata version back', async () => {
  let finishTags!: (response: Response) => void;
  vi.mocked(fetch)
    .mockResolvedValueOnce(json({ ...article(), updated_at: SECOND }))
    .mockReturnValueOnce(
      new Promise((resolve) => {
        finishTags = resolve;
      }),
    );
  await act(async () => editor.patch({ title: 'Pending headline' }));
  let saving!: Promise<unknown>;
  await act(async () => {
    saving = editor.save();
  });
  const third = '2026-01-01T00:00:10Z';
  await act(async () => editor.acceptWrite({ ...article(), updated_at: third }));
  await act(async () => {
    finishTags(json(['Saved tag']));
    await saving;
  });
  expect(editor.article?.updated_at).toBe(third);
  expect(editor.article?.tags).toEqual(['Saved tag']);
});
