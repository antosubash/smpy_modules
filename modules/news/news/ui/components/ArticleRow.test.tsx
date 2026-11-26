// @vitest-environment happy-dom
import { act } from 'react';
import { afterEach, describe, expect, it } from 'vitest';

import '../../pagebuilder-blocks';
import type { ArticleRead } from '../utils/types';
import { ArticleRow } from './ArticleRow';
import { cleanup, flush, mount } from './media/test-dom';

afterEach(cleanup);

const draft = {
  id: 7,
  title: 'Story',
  slug: 'story',
  category: '',
  status: 'draft',
  published_at: null,
  has_unpublished_changes: false,
  url: '/news/story',
  edit_url: '/admin/news/articles/7/body',
} as unknown as ArticleRead;

async function openMenu(canPublish: boolean): Promise<string> {
  await mount(
    <ul>
      <ArticleRow
        article={draft}
        busy={false}
        canPublish={canPublish}
        onSave={() => {}}
        onTrash={async () => {}}
        onPublish={async () => {}}
      />
    </ul>,
  );
  const trigger = document.querySelector<HTMLButtonElement>('button[aria-label^="More actions"]');
  await act(async () => {
    trigger?.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, button: 0 }));
    trigger?.click();
  });
  await flush();
  return document.body.textContent ?? '';
}

describe('Publish now on the list row', () => {
  it('is offered to someone holding news.publish', async () => {
    const text = await openMenu(true);
    expect(text).toContain('Edit the body');
    expect(text).toContain('Publish now');
  });

  it('is not offered without it, where the server would answer 403', async () => {
    const text = await openMenu(false);
    expect(text).toContain('Edit the body');
    expect(text).not.toContain('Publish now');
  });
});
