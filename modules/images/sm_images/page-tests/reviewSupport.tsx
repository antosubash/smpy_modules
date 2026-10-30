/** Shared stand-ins for the review page tests. */
import { vi } from 'vitest';

import { act, mount } from './test-dom';
import { collection, stubFetch } from './support';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));

const Review = (await import('../pages/Review')).default;

const SCHEMA = {
  type: 'object',
  properties: { n: { type: 'integer' }, kind: { type: 'string', enum: ['a', 'b'] } },
  required: ['n'],
};

export function item(id: number, overrides: Record<string, unknown> = {}) {
  return {
    id,
    prompt_id: 'p1',
    image_id: `i${id}`,
    group_id: null,
    status: 'completed',
    result_text: null,
    result_data: { n: id, kind: 'a' },
    error: null,
    cross_check: null,
    stale: false,
    review_status: 'unreviewed',
    reviewed_data: null,
    version: `v${id}`,
    prompt_name: 'count',
    output_schema: SCHEMA,
    filename: `${id}.jpg`,
    thumb_url: null,
    group_key: null,
    output_visible: true,
    ...overrides,
  };
}

export const LIST = 'GET /api/images/collections/c1/review';
export const prompts = { 'GET /api/images/collections/c1/prompts': { items: [] } };
export const reviewed = (id: number) => `POST /api/images/prompt-results/${id}/review`;

export async function open(routes: Record<string, unknown>) {
  const calls = stubFetch({ ...prompts, ...routes });
  const view = await mount(<Review collection={collection()} />);
  await act(async () => {});
  return { view, calls };
}

export const shown = (view: { find: (s: string) => HTMLElement | null }) =>
  view.find('[data-testid="images-review-panel"]')?.dataset.resultId;
export const posts = (calls: { method: string; body: unknown }[]) =>
  calls.filter((c) => c.method === 'POST').map((c) => c.body);

