// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useListFields } from './useListFields';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let result: ReturnType<typeof useListFields>;
let listKey = '';
function Harness() {
  result = useListFields(listKey);
  return null;
}

describe('useListFields', () => {
  let root: ReturnType<typeof createRoot>;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify([{ key: 'tags', ops: ['any'] }]), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    );
    vi.stubGlobal('fetch', fetchMock);
  });
  afterEach(() => {
    act(() => root.unmount());
    vi.unstubAllGlobals();
  });

  async function mount() {
    root = createRoot(document.createElement('div'));
    await act(async () => root.render(createElement(Harness)));
  }

  it('asks for nothing until a list is chosen', async () => {
    listKey = '';
    await mount();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result).toEqual({ fields: null, error: null });
  });

  it('loads the chosen list', async () => {
    listKey = 'news';
    await mount();
    expect(String(fetchMock.mock.calls[0][0])).toContain('/lists/news/fields');
    expect(result.fields).toEqual([{ key: 'tags', ops: ['any'] }]);
  });
});
