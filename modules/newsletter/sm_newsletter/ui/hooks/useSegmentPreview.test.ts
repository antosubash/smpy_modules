// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from '../utils/api';
import type { Rule } from '../utils/types';
import { COUNT_DEBOUNCE_MS } from './useAudienceCount';
import { useSegmentPreview } from './useSegmentPreview';

vi.mock('../utils/api', async (original) => ({
  ...(await original<typeof import('../utils/api')>()),
  api: { previewSegment: vi.fn() },
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const done: Rule = { field: 'a', op: 'is', value: 'x' };
const half: Rule = { field: 'b', op: 'is', value: '' };

let last: { count: number | null; error: string | null };

function Probe({ rules }: { rules: Rule[] }) {
  last = useSegmentPreview('news', rules);
  return null;
}

describe('useSegmentPreview', () => {
  let root: ReturnType<typeof createRoot>;
  const mount = (rules: Rule[]) => act(async () => root.render(createElement(Probe, { rules })));
  const wait = (ms: number) =>
    act(async () => {
      await new Promise((r) => setTimeout(r, ms));
    });

  beforeEach(() => {
    vi.mocked(api.previewSegment).mockReset().mockResolvedValue({ count: 7 });
    root = createRoot(document.body.appendChild(document.createElement('div')));
  });
  afterEach(() => {
    act(() => root.unmount());
    document.body.innerHTML = '';
  });

  it('sends only the complete rules', async () => {
    await mount([done, half]);
    await wait(COUNT_DEBOUNCE_MS + 100);
    expect(api.previewSegment).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.previewSegment).mock.calls[0][0]).toEqual({
      list_type_key: 'news',
      rules: [done],
    });
    expect(last.count).toBe(7);
  });

  it('does not re-ask when only an incomplete rule changes', async () => {
    await mount([done, half]);
    await wait(COUNT_DEBOUNCE_MS + 100);
    await mount([done, { ...half, field: 'c' }]);
    await wait(COUNT_DEBOUNCE_MS + 100);
    expect(api.previewSegment).toHaveBeenCalledTimes(1);
  });

  it('debounces a burst into one request', async () => {
    await mount([done]);
    await wait(100);
    await mount([{ ...done, value: 'y' }]);
    await wait(100);
    await mount([{ ...done, value: 'z' }]);
    expect(api.previewSegment).not.toHaveBeenCalled();
    await wait(COUNT_DEBOUNCE_MS + 100);
    expect(api.previewSegment).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.previewSegment).mock.calls[0][0].rules[0].value).toBe('z');
  });
});
