// @vitest-environment happy-dom
import { afterEach, describe, expect, it } from 'vitest';

import { mount } from '../test-dom';

const { useIsNarrow } = await import('./useIsNarrow');

type Hook = boolean;

function Probe({ onRender }: { onRender: (value: Hook) => void }) {
  onRender(useIsNarrow());
  return null;
}

/** The exact media query `useIsNarrow` asks the browser to evaluate, and
 *  whether it "matches" for this test's stubbed viewport. */
let lastQuery: string | undefined;

function stubMatchMedia(matches: boolean): void {
  window.matchMedia = ((query: string) => {
    lastQuery = query;
    return {
      matches,
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    };
  }) as unknown as typeof window.matchMedia;
}

describe('useIsNarrow — U8: the card breakpoint moved from sm to md', () => {
  afterEach(() => {
    // @ts-expect-error — undo the stub between tests
    window.matchMedia = undefined;
    lastQuery = undefined;
  });

  it('queries the md breakpoint (767.98px), not the old sm one (639.98px)', async () => {
    stubMatchMedia(false);
    let value: Hook = false;
    const view = await mount(<Probe onRender={(v) => (value = v)} />);
    expect(lastQuery).toBe('(max-width: 767.98px)');
    expect(value).toBe(false);
    await view.unmount();
  });

  it('reports narrow at 720px — the gap U8 closes between sm and md', async () => {
    // 720px is <= 767.98px (matches) but > 639.98px (would not have matched
    // the old query) — exactly the band the review found silently clipping.
    stubMatchMedia(true);
    let value: Hook = false;
    const view = await mount(<Probe onRender={(v) => (value = v)} />);
    expect(value).toBe(true);
    await view.unmount();
  });
});
