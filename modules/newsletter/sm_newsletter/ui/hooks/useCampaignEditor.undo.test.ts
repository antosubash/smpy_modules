// @vitest-environment happy-dom
import type { Data } from '@puckeditor/core';
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from '../utils/api';
import type { Block, CampaignDetail } from '../utils/types';
import { AUTOSAVE_DELAY_MS, useCampaignEditor } from './useCampaignEditor';

vi.mock('../utils/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../utils/api')>()),
  api: { getCampaign: vi.fn(), patchCampaign: vi.fn(), refreshCard: vi.fn() },
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const getCampaign = vi.mocked(api.getCampaign);
const patchCampaign = vi.mocked(api.patchCampaign);

function block(text: string): Block {
  return { type: 'Heading', props: { id: 'h1', text, level: '2', align: 'left' } };
}

function campaign(revision: number, body: Block[]): CampaignDetail {
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
    body,
  };
}

function data(text: string): Data {
  return { root: { props: {} }, content: [block(text)] };
}

let editor: ReturnType<typeof useCampaignEditor>;

function Harness() {
  editor = useCampaignEditor(7);
  return null;
}

let root: Root | null = null;

async function wait(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe('useCampaignEditor: undo during an in-flight save', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    getCampaign.mockReset();
    patchCampaign.mockReset();
    getCampaign.mockResolvedValue(campaign(3, [block('A')]));
  });
  afterEach(async () => {
    const mounted = root;
    root = null;
    if (mounted) await act(async () => mounted.unmount());
    vi.useRealTimers();
  });

  it('sends a follow-up save with the undone body, and flush waits for it', async () => {
    root = createRoot(document.createElement('div'));
    await act(async () => root?.render(createElement(Harness)));

    const first = deferred<CampaignDetail>();
    const second = deferred<CampaignDetail>();
    patchCampaign.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

    await act(async () => editor.onChange(data('B')));
    await wait(AUTOSAVE_DELAY_MS);
    expect(patchCampaign).toHaveBeenCalledTimes(1);
    expect(patchCampaign.mock.calls[0][1].body?.[0].props).toMatchObject({ text: 'B' });

    // Undo back to the saved body while B's save is still out.
    await act(async () => editor.onChange(data('A')));
    let flushed: boolean | null = null;
    await act(async () => {
      void editor.flush().then((ok) => {
        flushed = ok;
      });
    });

    await act(async () => first.resolve(campaign(4, [block('B')])));
    await wait(0);
    // The server now holds B while the canvas shows A: A must be sent.
    expect(patchCampaign).toHaveBeenCalledTimes(2);
    const [, payload] = patchCampaign.mock.calls[1];
    expect(payload.expected_revision).toBe(4);
    expect(payload.body?.[0].props).toMatchObject({ text: 'A' });
    expect(flushed).toBeNull();

    await act(async () => second.resolve(campaign(5, [block('A')])));
    await wait(0);
    expect(flushed).toBe(true);
    expect(editor.dirty).toBe(false);
    expect(editor.campaign?.revision).toBe(5);
  });
});
