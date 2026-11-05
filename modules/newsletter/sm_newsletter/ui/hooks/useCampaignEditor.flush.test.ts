// @vitest-environment happy-dom
// `flush` and `currentRevision`, what a real send relies on (A8). Its own file:
// `useCampaignEditor.test.ts` is at the 300-line cap.
import type { Data } from '@puckeditor/core';
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from '../utils/api';
import type { CampaignDetail } from '../utils/types';
import { AUTOSAVE_DELAY_MS, useCampaignEditor } from './useCampaignEditor';

vi.mock('../utils/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../utils/api')>()),
  api: { getCampaign: vi.fn(), patchCampaign: vi.fn(), refreshCard: vi.fn() },
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const getCampaign = vi.mocked(api.getCampaign);
const patchCampaign = vi.mocked(api.patchCampaign);

function campaign(revision: number): CampaignDetail {
  return {
    id: 7,
    name: 'Spring',
    subject: 'Hello',
    status: 'draft',
    list_type_key: 'news',
    revision,
    updated_at: null,
    recipient_count: 0,
    sent_count: 0,
    preheader: '',
    from_name: null,
    reply_to: null,
    audience: 'all',
    scheduled_at: null,
    started_at: null,
    finished_at: null,
    paused_code: null,
    paused_detail: null,
    failed_count: 0,
    bounced_count: 0,
    suppressed_count: 0,
    unsubscribe_count: 0,
    body: [],
  };
}

const heading = (text: string): Data => ({
  root: { props: {} },
  content: [{ type: 'Heading', props: { id: 'h1', text, level: '2', align: 'left' } }],
});

const unfinished: Data = {
  root: { props: {} },
  content: [
    { type: 'Heading', props: { id: 'h1', text: 'A', level: '2', align: 'left' } },
    { type: 'Image', props: { id: 'i1', src: '', alt: '', width: 600 } },
  ],
};

let editor: ReturnType<typeof useCampaignEditor>;
let root: Root | null = null;

function Harness() {
  editor = useCampaignEditor(7);
  return null;
}

describe('useCampaignEditor flush and currentRevision', () => {
  beforeEach(async () => {
    vi.useFakeTimers();
    getCampaign.mockReset().mockResolvedValue(campaign(3));
    patchCampaign.mockReset();
    root = createRoot(document.createElement('div'));
    await act(async () => root?.render(createElement(Harness)));
  });
  afterEach(async () => {
    const mounted = root;
    root = null;
    if (mounted) await act(async () => mounted.unmount());
    vi.useRealTimers();
  });

  it('flush resolves false while a block is unfinished', async () => {
    await act(async () => editor.onChange(unfinished));
    let ok: boolean | null = null;
    await act(async () => {
      ok = await editor.flush();
    });
    expect(ok).toBe(false);
    expect(patchCampaign).not.toHaveBeenCalled();
  });

  it('save (the test send) still resolves true around an unfinished block', async () => {
    await act(async () => editor.onChange(unfinished));
    let ok: boolean | null = null;
    await act(async () => {
      ok = await editor.save();
    });
    expect(ok).toBe(true);
  });

  it('currentRevision follows each successful save', async () => {
    expect(editor.currentRevision()).toBe(3);
    patchCampaign.mockResolvedValueOnce(campaign(4)).mockResolvedValueOnce(campaign(9));

    await act(async () => editor.onChange(heading('A')));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY_MS);
    });
    expect(editor.currentRevision()).toBe(4);

    await act(async () => editor.onChange(heading('AB')));
    let ok: boolean | null = null;
    await act(async () => {
      ok = await editor.flush();
    });
    expect(ok).toBe(true);
    expect(patchCampaign.mock.calls[1][1].expected_revision).toBe(4);
    expect(editor.currentRevision()).toBe(9);
  });
});
