// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { flush } from '../../page-tests/support';
import { mount } from '../../page-tests/test-dom';

// WebGL does not exist here: the canvas is the e2e's to prove.
vi.mock('./MapCanvas', () => ({
  default: ({ source }: { source: { features?: unknown[] } }) => (
    <div data-testid="fake-map" data-count={source.features?.length ?? 0} />
  ),
}));
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

  it("reads the points again when the collection's located images change (QA retest 2)", async () => {
    vi.mocked(resolveMapSource)
      .mockResolvedValueOnce({ kind: 'points', features: [point('a')] })
      .mockResolvedValueOnce({ kind: 'points', features: [point('a'), point('b')] });
    const el = (version: string) => (
      <CollectionMap pointsUrl="/p" mapUrl="/m" bbox={null} onSelect={() => {}} version={version} />
    );
    const view = await mount(el('1'));
    await flush();
    await flush();
    expect(view.find('[data-testid="fake-map"]')?.getAttribute('data-count')).toBe('1');
    await view.render(el('2'));
    // the drawn map stays while the fresh points load: no flash of "Loading"
    expect(view.find('[data-testid="fake-map"]')).not.toBeNull();
    await flush();
    await flush();
    expect(resolveMapSource).toHaveBeenCalledTimes(2);
    expect(view.find('[data-testid="fake-map"]')?.getAttribute('data-count')).toBe('2');
    await view.unmount();
  });

  it('keeps the drawn map when a refresh fails', async () => {
    vi.mocked(resolveMapSource)
      .mockResolvedValueOnce({ kind: 'points', features: [point('a')] })
      .mockRejectedValueOnce(new Error('503'));
    const el = (version: string) => (
      <CollectionMap pointsUrl="/p" mapUrl="/m" bbox={null} onSelect={() => {}} version={version} />
    );
    const view = await mount(el('1'));
    await flush();
    await flush();
    await view.render(el('2'));
    await flush();
    await flush();
    expect(view.find('[data-testid="fake-map"]')).not.toBeNull();
    await view.unmount();
  });

  it("never keeps another collection's map", async () => {
    vi.mocked(resolveMapSource)
      .mockResolvedValueOnce({ kind: 'points', features: [point('a')] })
      .mockRejectedValueOnce(new Error('503'));
    const el = (pointsUrl: string) => (
      <CollectionMap pointsUrl={pointsUrl} mapUrl="/m" bbox={null} onSelect={() => {}} />
    );
    const view = await mount(el('/p1'));
    await flush();
    await flush();
    await view.render(el('/p2'));
    expect(view.find('[data-testid="fake-map"]')).toBeNull(); // not /p1's points
    await flush();
    await flush();
    expect(view.find('[data-testid="fake-map"]')).toBeNull();
    await view.unmount();
  });
});
