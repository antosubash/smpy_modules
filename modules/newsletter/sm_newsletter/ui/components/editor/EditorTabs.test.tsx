// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import en from '../../../locales/en.json';
import { EditorTabs } from './EditorTabs';

vi.mock('../../utils/api', async (original) => ({
  ...(await original<typeof import('../../utils/api')>()),
  api: { testSend: vi.fn() },
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe('EditorTabs', () => {
  let root: ReturnType<typeof createRoot>;
  afterEach(() => {
    act(() => root.unmount());
    document.body.innerHTML = '';
  });

  async function mount(canSend: boolean) {
    root = createRoot(document.body.appendChild(document.createElement('div')));
    await act(async () =>
      root.render(
        createElement(EditorTabs, {
          tab: 'edit',
          onTab: () => {},
          campaignId: 1,
          canSend,
          maxRecipients: 5,
          flush: () => Promise.resolve(true),
          incomplete: false,
        }),
      ),
    );
    return [...document.querySelectorAll('button')].map((b) => b.textContent);
  }

  it('shows Send test only with can_send', async () => {
    expect(await mount(true)).toContain(en.test_send.trigger);
    act(() => root.unmount());
    document.body.innerHTML = '';
    expect(await mount(false)).not.toContain(en.test_send.trigger);
  });
});
