// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { click, mount, settle } from '../test-dom';
import type { RecordRead } from '../utils/types';

const visit = vi.fn();
const reload = vi.fn();
const success = vi.fn();
const createTranslation = vi.fn(async () => ({ uuid: 'de-uuid' }));

vi.mock('@inertiajs/react', () => ({
  router: { visit: (...a: unknown[]) => visit(...a), reload: (...a: unknown[]) => reload(...a) },
}));
vi.mock('sonner', () => ({
  toast: Object.assign(vi.fn(), { success: (...a: unknown[]) => success(...a), error: vi.fn() }),
}));
vi.mock('../utils/api-history', () => ({
  createTranslation: (...args: unknown[]) => createTranslation(...(args as [])),
}));

const { RecordTranslations } = await import('./RecordTranslations');

function record(): RecordRead {
  return {
    uuid: 'en-uuid',
    type_key: 'article',
    locale: 'en',
    display_title: 'Autumn Summit',
  } as unknown as RecordRead;
}

describe('RecordTranslations — U9: adding a translation says which language it created', () => {
  beforeEach(() => {
    visit.mockClear();
    success.mockClear();
    createTranslation.mockClear();
  });

  it('raises a success toast naming the language before navigating to the new sibling', async () => {
    const view = await mount(
      <RecordTranslations
        typeKey="article"
        record={record()}
        locales={['en', 'de']}
        translations={[]}
      />,
    );
    await click(view.find('[data-testid="records-translation-add-de"]'));
    await settle();
    expect(createTranslation).toHaveBeenCalledWith('article', 'en-uuid', { locale: 'de' });
    expect(success).toHaveBeenCalledOnce();
    expect(String(success.mock.calls[0][0])).toContain('translation created');
    expect(visit).toHaveBeenCalledWith('/admin/records/article/de-uuid');
    await view.unmount();
  });
});
