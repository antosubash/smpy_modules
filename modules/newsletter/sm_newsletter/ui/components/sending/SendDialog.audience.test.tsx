// @vitest-environment happy-dom
// An unfinished audience choice (a tag or segment kind with no value picked)
// blocks sending: wired as the editor page wires it, with the real hook and
// only `fetch` faked (Codex P1).
import { act, createElement, Fragment } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import en from '../../../locales/en.json';
import { campaign } from '../../hooks/campaignFixture';
import { AUTOSAVE_DELAY_MS, useCampaignEditor } from '../../hooks/useCampaignEditor';
import { AudiencePicker } from '../editor/AudiencePicker';
import { SendDialog } from './SendDialog';

vi.mock('@inertiajs/react', () => ({ router: { on: () => () => undefined } }));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const BASE = '/api/newsletter/campaigns/7';
const tags = {
  key: 'tags',
  label: 'Tags',
  type: 'choice',
  many: true,
  choices: [{ value: 'vip', label: 'VIP' }],
  system: false,
  ops: ['any'],
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

let requests: { method: string; url: string; body: Record<string, unknown> | null }[];
let root: Root | null;

function Harness() {
  const editor = useCampaignEditor(7);
  if (!editor.campaign) return null;
  return createElement(
    Fragment,
    null,
    createElement(AudiencePicker, {
      campaign: editor.campaign,
      readOnly: false,
      onChange: editor.saveMeta,
      onUnfinished: editor.holdAudience,
    }),
    createElement(SendDialog, {
      campaign: editor.campaign,
      canSend: true,
      onSent: () => undefined,
      flush: editor.flush,
      dirty: editor.dirty,
      incomplete: editor.incomplete,
      audienceUnfinished: editor.audienceUnfinished,
      currentRevision: editor.currentRevision,
    }),
  );
}

const sendButton = () =>
  [...document.querySelectorAll('button')].find(
    (b) => b.textContent === en.sending.send_button,
  ) as HTMLButtonElement;
const radio = (kind: string) =>
  document.querySelector(`[role="radio"][id$="-${kind}"]`) as HTMLButtonElement;
const wait = (ms: number) =>
  act(async () => {
    await new Promise((r) => setTimeout(r, ms));
  });
const writes = () => requests.filter((r) => r.method !== 'GET');

describe('an unfinished audience choice', () => {
  beforeEach(async () => {
    requests = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init: RequestInit = {}) => {
        const method = init.method ?? 'GET';
        const sent = init.body
          ? (JSON.parse(init.body as string) as Record<string, unknown>)
          : null;
        requests.push({ method, url, body: sent });
        if (url.endsWith('/lists/news/fields')) return json([tags]);
        if (url.includes('/segments')) return json([]);
        if (url.includes('/audience-count')) return json({ count: 5 });
        if (url.startsWith(`${BASE}/estimate`))
          return json({
            recipients: 5,
            estimated_finish: '2026-12-01T10:00:00Z',
            overlaps: false,
            daily_rate: 10,
          });
        if (method === 'PATCH') return json({ ...campaign(8), id: 7, ...sent });
        if (url === `${BASE}/send`) return json({ ...campaign(9), id: 7, status: 'sending' });
        return json({ ...campaign(3), id: 7 });
      }),
    );
    root = createRoot(document.body.appendChild(document.createElement('div')));
    await act(async () => root?.render(createElement(Harness)));
    await wait(50);
  });
  afterEach(async () => {
    const mounted = root;
    root = null;
    if (mounted) await act(async () => mounted.unmount());
    vi.unstubAllGlobals();
    document.body.innerHTML = '';
  });

  it('disables Send and schedules nothing until a tag is chosen', async () => {
    expect(sendButton().disabled).toBe(false);
    await act(async () => radio('tag').click());
    expect(sendButton().disabled).toBe(true);
    expect(sendButton().title).toBe(en.sending.dialog.audience_unfinished);
    // Even if the dialog opened, Confirm must send nothing.
    await act(async () => sendButton().click());
    await wait(50);
    const confirm = [...document.querySelectorAll('button')].find(
      (b) => b.textContent === en.sending.dialog.confirm,
    );
    if (confirm) await act(async () => confirm.click());
    await wait(AUTOSAVE_DELAY_MS + 100);
    expect(writes()).toEqual([]);
  });

  it('lets Send go again once the choice is reverted or completed', async () => {
    await act(async () => radio('tag').click());
    await act(async () => radio('all').click());
    expect(sendButton().disabled).toBe(false);
    await act(async () => radio('tag').click());
    const select = document.querySelector('select[id$="-tag"]') as HTMLSelectElement;
    await act(async () => {
      select.value = 'vip';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(sendButton().disabled).toBe(false);
  });
});
