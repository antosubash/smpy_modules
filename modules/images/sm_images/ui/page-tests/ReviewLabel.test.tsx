// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { item, LIST, open } from './reviewSupport';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));

afterEach(() => vi.unstubAllGlobals());

describe('review output (QA retest 2, R2-REVIEW-LABEL)', () => {
  it('names the output by its prompt, not its id', async () => {
    const { view } = await open({ [LIST]: { items: [item(1)], next_cursor: null } });
    const titles = view.all('[data-testid="images-result-title"]').map((n) => n.textContent);
    expect(titles.length).toBeGreaterThan(0);
    expect(titles.every((x) => x === 'count')).toBe(true); // reviewSupport's prompt_name
    expect(view.find('[data-testid="images-result-title"]')?.getAttribute('title')).toBe('p1');
    await view.unmount();
  });
});
