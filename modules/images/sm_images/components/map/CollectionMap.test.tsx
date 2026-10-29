// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { flush } from '../../page-tests/support';
import { mount } from '../../test-dom';

// WebGL does not exist here: the canvas is the e2e's to prove.
vi.mock('./MapCanvas', () => ({ default: () => <div data-testid="fake-map" /> }));
vi.mock('./mapSource', async (real) => ({
  ...(await real<typeof import('./mapSource')>()),
  resolveMapSource: vi.fn(),
}));

const { CollectionMap } = await import('./CollectionMap');
const { resolveMapSource } = await import('./mapSource');

const point = (id: string) => ({
  type: 'Feature' as const,
  geometry: { type: 'Point' as const, coordinates: [1, 2] as [number, number] },
  properties: { id, captured_at: null, group_id: null },
});

afterEach(() => vi.mocked(resolveMapSource).mockReset());

async function render() {
  const view = await mount(
    <CollectionMap pointsUrl="/p" mapUrl="/m" bbox={null} onSelect={() => {}} />,
  );
  await flush();
  await flush();
  return view;
}

describe('CollectionMap (review of QA round 1)', () => {
  it('says when the points fallback stopped at its cap', async () => {
    vi.mocked(resolveMapSource).mockResolvedValue({
      kind: 'points',
      features: [point('a'), point('b')],
      truncated: true,
    } as never);
    const view = await render();
    expect(view.find('[data-testid="images-map-truncated"]')?.textContent).toBe(
      'Showing the first 2 located images.',
    );
    await view.unmount();
  });

  it('says nothing when every point is drawn', async () => {
    vi.mocked(resolveMapSource).mockResolvedValue({ kind: 'points', features: [point('a')] });
    const view = await render();
    expect(view.find('[data-testid="fake-map"]')).not.toBeNull();
    expect(view.find('[data-testid="images-map-truncated"]')).toBeNull();
    await view.unmount();
  });
});
