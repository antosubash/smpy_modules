// @vitest-environment happy-dom
import type { Data } from '@puckeditor/core';
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from '../utils/api';
import { HttpError } from '../utils/http';
import type { CampaignDetail } from '../utils/types';
import { AUTOSAVE_DELAY_MS, useCampaignEditor } from './useCampaignEditor';

vi.mock('../utils/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../utils/api')>()),
  api: { getCampaign: vi.fn(), patchCampaign: vi.fn(), refreshCard: vi.fn() },
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const getCampaign = vi.mocked(api.getCampaign);
const patchCampaign = vi.mocked(api.patchCampaign);
const refreshCard = vi.mocked(api.refreshCard);

function campaign(revision: number, body: CampaignDetail['body'] = []): CampaignDetail {
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
  return {
    root: { props: {} },
    content: [{ type: 'Heading', props: { id: 'h1', text, level: '2', align: 'left' } }],
  };
}

let editor: ReturnType<typeof useCampaignEditor>;

function Harness() {
  editor = useCampaignEditor(7);
  return null;
}

let root: Root | null = null;

async function mount() {
  root = createRoot(document.createElement('div'));
  await act(async () => root?.render(createElement(Harness)));
}

async function unmount() {
  const mounted = root;
  root = null;
  if (mounted) await act(async () => mounted.unmount());
}

async function wait(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe('useCampaignEditor', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    getCampaign.mockReset();
    patchCampaign.mockReset();
    refreshCard.mockReset();
    getCampaign.mockResolvedValue(campaign(3));
  });
  afterEach(async () => {
    await unmount();
    vi.useRealTimers();
  });

  it('debounces saves', async () => {
    patchCampaign.mockResolvedValue(campaign(4));
    await mount();
    expect(editor.campaign?.id).toBe(7);

    await act(async () => editor.onChange(data('A')));
    await wait(AUTOSAVE_DELAY_MS - 500);
    await act(async () => editor.onChange(data('AB')));
    await wait(AUTOSAVE_DELAY_MS - 1);
    expect(patchCampaign).not.toHaveBeenCalled();

    await wait(1);
    expect(patchCampaign).toHaveBeenCalledTimes(1);
    const [, payload] = patchCampaign.mock.calls[0];
    expect(payload.body?.[0].props).toMatchObject({ id: 'h1', text: 'AB' });
    expect(editor.status).toBe('saved');
  });

  it("sends expected_revision and adopts the response's", async () => {
    patchCampaign.mockResolvedValueOnce(campaign(4)).mockResolvedValueOnce(campaign(5));
    await mount();

    await act(async () => editor.onChange(data('A')));
    await wait(AUTOSAVE_DELAY_MS);
    expect(patchCampaign.mock.calls[0][1].expected_revision).toBe(3);

    await act(async () => editor.saveMeta({ subject: 'New subject' }));
    await wait(AUTOSAVE_DELAY_MS);
    expect(patchCampaign).toHaveBeenCalledTimes(2);
    const [, second] = patchCampaign.mock.calls[1];
    expect(second.expected_revision).toBe(4);
    expect(second.subject).toBe('New subject');
    // The body did not change since the first save, so it is not resent.
    expect(second.body).toBeUndefined();
    expect(editor.campaign?.revision).toBe(5);
  });

  it('stale stops autosave', async () => {
    patchCampaign.mockRejectedValue(new HttpError('stale', 409, 'stale'));
    await mount();

    await act(async () => editor.onChange(data('A')));
    await wait(AUTOSAVE_DELAY_MS);
    expect(editor.status).toBe('stale');
    expect(patchCampaign).toHaveBeenCalledTimes(1);

    await act(async () => editor.onChange(data('AB')));
    await act(async () => editor.saveMeta({ name: 'Other' }));
    await wait(AUTOSAVE_DELAY_MS * 3);
    expect(patchCampaign).toHaveBeenCalledTimes(1);
    expect(editor.status).toBe('stale');
  });

  it('does not save a body with an unfinished block', async () => {
    patchCampaign.mockResolvedValue(campaign(4));
    await mount();

    const unfinished: Data = {
      root: { props: {} },
      content: [{ type: 'Image', props: { id: 'i1', src: '', alt: '', width: 600 } }],
    };
    await act(async () => editor.onChange(unfinished));
    await wait(AUTOSAVE_DELAY_MS);
    expect(patchCampaign).not.toHaveBeenCalled();
    expect(editor.incomplete).toBe(true);
  });

  it('refresh flushes the pending autosave before refreshing', async () => {
    const card = (title: string) => ({
      type: 'PageCard' as const,
      props: { id: 'c1', source_id: 9, title, url: '/p/x', snapshot_at: '2026-11-01T00:00:00Z' },
    });
    const heading = {
      type: 'Heading' as const,
      props: { id: 'h1', text: 'A', level: '2', align: 'left' },
    };
    getCampaign.mockResolvedValue(campaign(3, [card('Old')]));
    let release: (value: CampaignDetail) => void = () => {};
    patchCampaign.mockReturnValue(
      new Promise<CampaignDetail>((resolve) => {
        release = resolve;
      }),
    );
    refreshCard.mockResolvedValue(campaign(5, [heading, card('New')]));
    await mount();

    await act(async () =>
      editor.onChange({ root: { props: {} }, content: [heading, card('Old')] }),
    );
    let done = false;
    await act(async () => {
      void editor.refresh('c1').then(() => {
        done = true;
      });
    });
    // The pending edit is sent at once, without waiting for the debounce...
    expect(patchCampaign).toHaveBeenCalledTimes(1);
    expect(patchCampaign.mock.calls[0][1].body?.[0].props.id).toBe('h1');
    // ...and the refresh waits for it.
    expect(refreshCard).not.toHaveBeenCalled();

    await act(async () => release(campaign(4, [heading, card('Old')])));
    await wait(0);
    expect(refreshCard).toHaveBeenCalledWith(7, 'c1', 4);
    expect(done).toBe(true);
    expect(editor.campaign?.revision).toBe(5);
    expect(editor.data.content.map((item) => item.props.title ?? item.props.text)).toEqual([
      'A',
      'New',
    ]);

    // Nothing is left to autosave afterwards.
    await wait(AUTOSAVE_DELAY_MS * 2);
    expect(patchCampaign).toHaveBeenCalledTimes(1);
  });

  it('does not refresh when the pending autosave failed', async () => {
    patchCampaign.mockRejectedValue(new HttpError('boom', 500));
    await mount();
    await act(async () => editor.onChange(data('A')));
    await act(async () => editor.refresh('c1'));
    expect(refreshCard).not.toHaveBeenCalled();
    expect(editor.status).toBe('error');
  });

  it('tracks dirty until the server holds every edit', async () => {
    patchCampaign.mockRejectedValueOnce(new HttpError('boom', 500)).mockResolvedValue(campaign(4));
    await mount();
    expect(editor.dirty).toBe(false);

    await act(async () => editor.onChange(data('A')));
    expect(editor.dirty).toBe(true); // waiting for the debounce
    await wait(AUTOSAVE_DELAY_MS);
    expect(editor.status).toBe('error');
    expect(editor.dirty).toBe(true); // the failed edit is still only here

    await act(async () => editor.onChange(data('AB')));
    await wait(AUTOSAVE_DELAY_MS);
    expect(editor.status).toBe('saved');
    expect(editor.dirty).toBe(false);

    const unfinished: Data = {
      root: { props: {} },
      content: [{ type: 'Image', props: { id: 'i1', src: '', alt: '', width: 600 } }],
    };
    await act(async () => editor.onChange(unfinished));
    expect(editor.dirty).toBe(true); // held back by the unfinished block
  });

  it('flushes edits left over after a failed save on unmount', async () => {
    patchCampaign.mockRejectedValueOnce(new HttpError('boom', 500)).mockResolvedValue(campaign(4));
    await mount();
    await act(async () => editor.onChange(data('A')));
    await wait(AUTOSAVE_DELAY_MS);
    expect(patchCampaign).toHaveBeenCalledTimes(1);

    // No timer is pending now; leaving must still send what is unsaved.
    await unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(patchCampaign).toHaveBeenCalledTimes(2);
    expect(patchCampaign.mock.calls[1][1].body?.[0].props.text).toBe('A');
  });

  it('does not resend the saved body in another key order', async () => {
    getCampaign.mockResolvedValue(
      campaign(3, [{ type: 'Heading', props: { id: 'h1', text: 'A', level: '2', align: 'left' } }]),
    );
    await mount();
    // Puck puts `id` last on a block it inserted; the server puts it first.
    await act(async () =>
      editor.onChange({
        root: { props: {} },
        content: [{ type: 'Heading', props: { text: 'A', level: '2', align: 'left', id: 'h1' } }],
      }),
    );
    await wait(AUTOSAVE_DELAY_MS * 2);
    expect(patchCampaign).not.toHaveBeenCalled();
    expect(editor.dirty).toBe(false);
  });

  it('a stale refresh marks the editor stale', async () => {
    refreshCard.mockRejectedValue(new HttpError('stale', 409, 'not_a_draft'));
    await mount();
    await act(async () => editor.refresh('card1'));
    expect(editor.status).toBe('stale');
  });
});
