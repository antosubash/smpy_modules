// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import en from '../../../locales/en.json';
import { campaign } from '../../hooks/campaignFixture';
import { api } from '../../utils/api';
import { HttpError } from '../../utils/http';
import type { ListField, Segment } from '../../utils/types';
import { AudiencePicker } from './AudiencePicker';

vi.mock('../../utils/api', async (original) => ({
  ...(await original<typeof import('../../utils/api')>()),
  api: { listFields: vi.fn(), listSegments: vi.fn(), audienceCount: vi.fn() },
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const copy = en.audience;
const tagsField: ListField = {
  key: 'tags',
  label: 'Tags',
  type: 'choice',
  many: true,
  choices: [
    { value: 'vip', label: 'VIP' },
    { value: 'beta', label: 'Beta' },
  ],
  system: false,
  ops: ['any'],
};
const segment: Segment = {
  id: 3,
  name: 'Active',
  list_type_key: 'news',
  rules: [],
  updated_at: null,
};

describe('AudiencePicker', () => {
  let root: ReturnType<typeof createRoot>;
  const onChange = vi.fn();

  beforeEach(() => {
    onChange.mockReset();
    vi.mocked(api.listFields).mockReset().mockResolvedValue([tagsField]);
    vi.mocked(api.listSegments).mockReset().mockResolvedValue([segment]);
    vi.mocked(api.audienceCount).mockReset().mockResolvedValue({ count: 42 });
  });
  afterEach(() => {
    act(() => root.unmount());
    document.body.innerHTML = '';
  });

  async function render(audience = 'all', readOnly = false) {
    const host = document.body.appendChild(document.createElement('div'));
    root = createRoot(host);
    const c = { ...campaign(1), audience };
    await act(async () =>
      root.render(createElement(AudiencePicker, { campaign: c, readOnly, onChange })),
    );
    await act(async () => {
      await new Promise((r) => setTimeout(r, 400));
    });
  }
  const radio = (label: string) =>
    document.querySelector(`[role="radio"][id$="-${label}"]`) as HTMLButtonElement | null;
  const select = (id: string) =>
    document.querySelector(`select[id$="-${id}"]`) as HTMLSelectElement;
  async function choose(el: HTMLSelectElement, value: string) {
    await act(async () => {
      el.value = value;
      el.dispatchEvent(new Event('change', { bubbles: true }));
    });
  }

  it('saves a chosen tag as tag:<value>', async () => {
    await render();
    await act(async () => radio('tag')?.click());
    expect(onChange).not.toHaveBeenCalled();
    await choose(select('tag'), 'vip');
    expect(onChange).toHaveBeenCalledWith({ audience: 'tag:vip' });
  });

  it('saves a chosen segment', async () => {
    await render();
    await act(async () => radio('segment')?.click());
    await choose(select('segment'), '3');
    expect(onChange).toHaveBeenCalledWith({ audience: 'segment:3' });
  });

  it('hides the tag option when the list has no tags field', async () => {
    vi.mocked(api.listFields).mockResolvedValue([]);
    await render();
    expect(radio('tag')).toBeNull();
    expect(radio('segment')).not.toBeNull();
  });

  it('warns about a saved segment that no longer exists', async () => {
    await render('segment:99');
    expect(document.body.textContent).toContain(copy.segment_missing);
  });

  it('warns about a saved tag that is no longer a choice', async () => {
    await render('tag:gone');
    expect(document.body.textContent).toContain(copy.tag_missing);
  });

  it('does not warn about a saved tag that is still a choice', async () => {
    await render('tag:vip');
    expect(document.body.textContent).not.toContain(copy.tag_missing);
  });

  it('shows the error, not "counting", when the count fails', async () => {
    vi.mocked(api.audienceCount).mockRejectedValue(new HttpError('x', 422, 'invalid_audience'));
    await render('tag:vip');
    expect(document.body.textContent).toContain(en.errors.invalid_audience);
    expect(document.body.textContent).not.toContain(copy.count_loading);
  });

  it('is disabled when read-only', async () => {
    await render('tag:vip', true);
    expect(radio('all')?.disabled).toBe(true);
    expect(select('tag').disabled).toBe(true);
  });

  it('shows the count', async () => {
    await render();
    expect(api.audienceCount).toHaveBeenCalledWith('news', 'all', expect.any(AbortSignal));
    expect(document.body.textContent).toContain('About 42 subscribers');
  });

  it('says "1 subscriber" for one', async () => {
    vi.mocked(api.audienceCount).mockResolvedValue({ count: 1 });
    await render();
    expect(document.body.textContent).toContain('About 1 subscriber');
    expect(document.body.textContent).not.toContain('About 1 subscribers');
  });
});
