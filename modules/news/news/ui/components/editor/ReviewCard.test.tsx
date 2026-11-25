// @vitest-environment happy-dom
import { act } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import '../../../pagebuilder-blocks';
import type { ArticleWrite } from '../../hooks/useArticleEditor';
import type { ArticleRead } from '../../utils/types';
import { button, cleanup, flush, mount } from '../media/test-dom';
import { ReviewCard } from './ReviewCard';

const published = {
  id: 7,
  title: 'Story',
  slug: 'story',
  status: 'published',
  updated_at: '2026-01-01T00:00:00Z',
} as unknown as ArticleRead;

/** What the editor's write queue does with a failing action: report it as `false`. */
const queued: ArticleWrite = async (action) => {
  try {
    await action(null);
    return true;
  } catch {
    return false;
  }
};

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: 'stale', code: 'article_conflict' }), {
          status: 409,
          headers: { 'Content-Type': 'application/json' },
        }),
    ),
  );
});
afterEach(cleanup);

describe('unpublish after a conflict', () => {
  it('keeps the dialog open and shows the conflict message, not the generic one', async () => {
    await mount(<ReviewCard article={published} canPublish writeArticle={queued} />);
    await act(async () => button('Unpublish')?.click());
    await flush();
    const dialog = document.querySelector('[role="alertdialog"]');
    expect(dialog).not.toBeNull();
    const confirm = [...(dialog?.querySelectorAll('button') ?? [])].find(
      (b) => b.textContent?.trim() === 'Unpublish',
    );
    await act(async () => confirm?.click());
    // The card holds its in-flight guard for a cooldown after a transition.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 1000));
    });
    const open = document.querySelector('[role="alertdialog"]');
    expect(open?.textContent).toContain('This article was changed somewhere else');
    expect(open?.textContent).not.toContain('Could not unpublish');
  });
});
