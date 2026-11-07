// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import en from '../../../locales/en.json';
import { api } from '../../utils/api';
import { NewCampaignDialog } from './NewCampaignDialog';

vi.mock('@inertiajs/react', () => ({ router: { visit: vi.fn() } }));
vi.mock('../../utils/api', () => ({
  api: { lists: vi.fn(), createCampaign: vi.fn() },
  errorMessage: () => 'failed',
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const copy = en.campaigns.new;

describe('NewCampaignDialog', () => {
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    vi.mocked(api.lists).mockReset();
  });
  afterEach(() => {
    act(() => root.unmount());
    document.body.innerHTML = '';
  });

  async function open(lists: string[]) {
    vi.mocked(api.lists).mockResolvedValue(lists);
    root = createRoot(document.body.appendChild(document.createElement('div')));
    await act(async () => root.render(createElement(NewCampaignDialog)));
    const trigger = [...document.querySelectorAll('button')].find(
      (b) => b.textContent === copy.trigger,
    );
    await act(async () => trigger?.click());
  }

  const createButton = () =>
    [...document.querySelectorAll('button')].find((b) => b.textContent === copy.create);

  it('disables create without a list', async () => {
    await open(['news', 'offers']);
    const name = document.querySelector('input') as HTMLInputElement;
    await act(async () => {
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
      set?.call(name, 'Spring');
      name.dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect(document.querySelector('select')).not.toBeNull();
    expect((createButton() as HTMLButtonElement).disabled).toBe(true);
  });

  it('shows the no-lists note', async () => {
    await open([]);
    expect(document.body.textContent).toContain(copy.no_lists);
    expect(document.querySelector('select')).toBeNull();
    expect((createButton() as HTMLButtonElement).disabled).toBe(true);
  });

  it('creates once for clicks in the same tick', async () => {
    vi.mocked(api.createCampaign).mockReset();
    vi.mocked(api.createCampaign).mockReturnValue(new Promise(() => {}));
    await open(['news']);
    const name = document.querySelector('input') as HTMLInputElement;
    const select = document.querySelector('select') as HTMLSelectElement;
    await act(async () => {
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
      set?.call(name, 'Spring');
      name.dispatchEvent(new Event('input', { bubbles: true }));
      select.value = 'news';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    const form = document.querySelector('form') as HTMLFormElement;
    await act(async () => {
      for (let i = 0; i < 5; i++) form.requestSubmit();
    });
    expect(api.createCampaign).toHaveBeenCalledTimes(1);
  });
});
