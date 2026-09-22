// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { act, click, mount } from '../test-dom';
import type { RecordPage, RecordRead, TypeRead } from '../utils/types';

let getOptions: { onStart?: () => void; onFinish?: () => void } | undefined;
const get = vi.fn((_url: string, _params: unknown, options: typeof getOptions) => {
  getOptions = options;
});

vi.mock('@inertiajs/react', () => ({
  Head: () => null,
  Link: ({ children, href }: { children?: unknown; href: string }) => (
    <a href={href}>{children as React.ReactNode}</a>
  ),
  usePage: () => ({ url: '/admin/records/book?page=2', props: { auth: { permissions: [] } } }),
  router: {
    get: (...args: [string, unknown, typeof getOptions]) => get(...args),
    reload: vi.fn(),
    visit: vi.fn(),
  },
}));
vi.mock('../components/RecordIoMenu', () => ({ RecordIoMenu: () => null }));
vi.mock('../components/RecordsToaster', () => ({ RecordsToaster: () => null }));

const RecordList = (await import('./RecordList')).default;

function type(): TypeRead {
  return {
    key: 'book',
    label: 'Book',
    label_plural: 'Books',
    fields: [],
    display_field: null,
  } as unknown as TypeRead;
}

function record(uuid: string): RecordRead {
  return {
    uuid,
    type_key: 'book',
    status: 'draft',
    slug: null,
    locale: 'en',
    translation_group: null,
    display_title: `Book ${uuid}`,
    position: 0,
    version: 1,
    schema_version: 1,
    published_at: null,
    created_at: '2026-01-01T00:00:00+00:00',
    updated_at: '2026-01-01T00:00:00+00:00',
    is_deleted: false,
    data: {},
    invalid: [],
  } as unknown as RecordRead;
}

function records(): RecordPage {
  return {
    items: Array.from({ length: 25 }, (_, i) => record(`r${i}`)),
    total: 100,
    total_capped: false,
    page: 2,
    page_size: 25,
    next_cursor: null,
  };
}

describe('RecordList — U12: a page change shows itself instead of asserting stale data', () => {
  beforeEach(() => {
    get.mockClear();
    getOptions = undefined;
  });

  it('sets aria-busy and dims the list wrapper for the duration of the request', async () => {
    const view = await mount(<RecordList type={type()} records={records()} />);
    const wrapper = () => view.find('[data-testid="records-list-wrapper"]');
    expect(wrapper()?.getAttribute('aria-busy')).toBe('false');

    await click(view.button('Next'));
    expect(get).toHaveBeenCalledOnce();
    expect(getOptions?.onStart).toBeTypeOf('function');
    await act(async () => {
      getOptions?.onStart?.();
    });
    expect(wrapper()?.getAttribute('aria-busy')).toBe('true');
    expect(wrapper()?.className).toContain('opacity-60');

    await act(async () => {
      getOptions?.onFinish?.();
    });
    expect(wrapper()?.getAttribute('aria-busy')).toBe('false');
    expect(wrapper()?.className).not.toContain('opacity-60');
    await view.unmount();
  });
});
