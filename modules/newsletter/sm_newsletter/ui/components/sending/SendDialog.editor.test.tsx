// @vitest-environment happy-dom
// SendDialog wired to the real `useCampaignEditor` (A8): only `fetch` is faked,
// so what is checked is the order and the revision of the requests that leave.
import type { Data } from '@puckeditor/core';
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import en from '../../../locales/en.json';
import { useCampaignEditor } from '../../hooks/useCampaignEditor';
import type { CampaignDetail } from '../../utils/types';
import { SendDialog } from './SendDialog';

vi.mock('@inertiajs/react', () => ({ router: { on: () => () => undefined } }));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const copy = en.sending;
const BASE = '/api/newsletter/campaigns/7';

function campaign(revision: number, status = 'draft'): CampaignDetail {
  return {
    id: 7,
    name: 'Spring',
    subject: 'Hello',
    status,
    list_type_key: 'news',
    revision,
    updated_at: null,
    recipient_count: 0,
    sent_count: 0,
    preheader: '',
    from_name: null,
    reply_to: null,
    audience: 'all',
    body: [{ type: 'Heading', props: { id: 'h1', text: 'A', level: '2', align: 'left' } }],
    scheduled_at: null,
    started_at: null,
    finished_at: null,
    paused_code: null,
    paused_detail: null,
    failed_count: 0,
    bounced_count: 0,
    suppressed_count: 0,
    unsubscribe_count: 0,
  };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const body = (text: string, extra: Data['content'] = []): Data => ({
  root: { props: {} },
  content: [{ type: 'Heading', props: { id: 'h1', text, level: '2', align: 'left' } }, ...extra],
});

let requests: { method: string; url: string; body: Record<string, unknown> | null }[];
let patchResponse: () => Response;
let editor: ReturnType<typeof useCampaignEditor>;
let root: Root | null;

function Harness() {
  editor = useCampaignEditor(7);
  if (!editor.campaign) return null;
  return createElement(SendDialog, {
    campaign: editor.campaign,
    canSend: true,
    onSent: () => undefined,
    flush: editor.flush,
    dirty: editor.dirty,
    incomplete: editor.incomplete,
    currentRevision: editor.currentRevision,
  });
}

const button = (label: string) =>
  [...document.querySelectorAll('button')].find((b) => b.textContent === label) as
    | HTMLButtonElement
    | undefined;

const sends = () => requests.filter((r) => r.url === `${BASE}/send`);

describe('SendDialog with the real editor hook', () => {
  beforeEach(async () => {
    requests = [];
    patchResponse = () => json(campaign(8));
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init: RequestInit = {}) => {
        const method = init.method ?? 'GET';
        const sent = init.body
          ? (JSON.parse(init.body as string) as Record<string, unknown>)
          : null;
        requests.push({ method, url, body: sent });
        if (method === 'PATCH') return patchResponse();
        if (url.startsWith(`${BASE}/estimate`))
          return json({
            recipients: 2,
            estimated_finish: '2026-12-01T10:00:00Z',
            overlaps: false,
            daily_rate: 10,
          });
        if (url === `${BASE}/send`) return json(campaign(9, 'sending'));
        return json(campaign(3));
      }),
    );
    root = createRoot(document.body.appendChild(document.createElement('div')));
    await act(async () => root?.render(createElement(Harness)));
  });
  afterEach(async () => {
    const mounted = root;
    root = null;
    if (mounted) await act(async () => mounted.unmount());
    vi.unstubAllGlobals();
    document.body.innerHTML = '';
  });

  it('cannot be opened while a block is unfinished, and sends nothing', async () => {
    await act(async () =>
      editor.onChange(
        body('A', [{ type: 'Image', props: { id: 'i1', src: '', alt: '', width: 600 } }]),
      ),
    );
    expect(button(copy.send_button)?.disabled).toBe(true);
    await act(async () => button(copy.send_button)?.click());
    expect(sends()).toEqual([]);
  });

  it('saves an edit made just before Confirm, then sends with that save’s revision', async () => {
    await act(async () => button(copy.send_button)?.click());
    await act(async () => editor.onChange(body('AB')));
    await act(async () => button(copy.dialog.confirm)?.click());

    const writes = requests.filter((r) => r.method !== 'GET');
    expect(writes.map((r) => `${r.method} ${r.url}`)).toEqual([
      `PATCH ${BASE}`,
      `POST ${BASE}/send`,
    ]);
    expect(writes[0].body?.expected_revision).toBe(3);
    expect(writes[1].body).toEqual({ expected_revision: 8, scheduled_at: null });
  });

  it('sends nothing when the save is refused as stale', async () => {
    patchResponse = () => json({ detail: 'stale', code: 'stale' }, 409);
    await act(async () => button(copy.send_button)?.click());
    await act(async () => editor.onChange(body('AB')));
    await act(async () => button(copy.dialog.confirm)?.click());

    expect(requests.some((r) => r.method === 'PATCH')).toBe(true);
    expect(sends()).toEqual([]);
    expect(document.body.textContent).toContain(en.test_send.unsaved);
  });
});
