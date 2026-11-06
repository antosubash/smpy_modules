// @vitest-environment happy-dom
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
    body,
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

describe('useCampaignEditor, unsaveable edits', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    getCampaign.mockReset();
    patchCampaign.mockReset();
    getCampaign.mockResolvedValue(campaign(3));
  });
  afterEach(async () => {
    await unmount();
    vi.useRealTimers();
  });

  it('an unsaveable details field keeps the editor dirty until it is fixed', async () => {
    patchCampaign.mockResolvedValue(campaign(4));
    await mount();

    await act(async () => editor.markMetaInvalid('reply_to', true));
    expect(editor.metaInvalid).toBe(true);
    expect(editor.dirty).toBe(true);
    await wait(AUTOSAVE_DELAY_MS);
    expect(patchCampaign).not.toHaveBeenCalled();

    await act(async () => editor.markMetaInvalid('reply_to', false));
    expect(editor.metaInvalid).toBe(false);
    expect(editor.dirty).toBe(false);
  });

  it('clears the error banner on the next successful save', async () => {
    patchCampaign
      .mockRejectedValueOnce(new HttpError('boom', 500, 'server_error'))
      .mockResolvedValueOnce(campaign(4));
    await mount();

    await act(async () => editor.saveMeta({ subject: 'One' }));
    await wait(AUTOSAVE_DELAY_MS);
    expect(editor.status).toBe('error');
    expect(editor.error).not.toBeNull();

    await act(async () => editor.saveMeta({ subject: 'Two' }));
    await wait(AUTOSAVE_DELAY_MS);
    expect(editor.status).toBe('saved');
    expect(editor.error).toBeNull();
  });
});
