import { afterEach, describe, expect, it, vi } from 'vitest';

import en from '../../locales/en.json';
import type { Translate } from './i18n';

vi.mock('@inertiajs/react', () => ({ router: { on: () => () => undefined } }));

/** A fresh copy of the modules, loaded under a page that rendered `props`. */
async function load(props: unknown) {
  vi.resetModules();
  const text = JSON.stringify({ component: 'Newsletter/Campaigns', props });
  vi.stubGlobal('document', {
    querySelector: (selector: string) =>
      selector.includes('data-page="app"') ? { textContent: text } : null,
  });
  return { api: (await import('./api')).api, http: await import('./http') };
}

function stubFetch(response: () => Response) {
  const fetchMock = vi.fn().mockImplementation(async () => response());
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

const ok = () => new Response('{}', { status: 200 });

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('sends csrf header on writes', () => {
  it('on every write verb, and not on a read', async () => {
    const { api } = await load({ csrf_token: 'tok' });
    const fetchMock = stubFetch(ok);
    await api.createCampaign({ name: 'n', list_type_key: 'l' });
    await api.patchCampaign(1, { expected_revision: 1, name: 'x' });
    await api.putSettings({ daily_limit: 5 });
    await api.putPassword('pw');
    await api.refreshCard(1, 'b1', 2);
    await api.getCampaign(1);
    const sent = fetchMock.mock.calls.map((c) => ({
      url: c[0] as string,
      method: (c[1] as RequestInit).method ?? 'GET',
      token: new Headers((c[1] as RequestInit).headers).get('X-CSRF-Token'),
    }));
    expect(sent.slice(0, 5).map((s) => s.token)).toEqual(['tok', 'tok', 'tok', 'tok', 'tok']);
    expect(sent[5].token).toBeNull();
    expect(sent.map((s) => `${s.method} ${s.url}`)).toEqual([
      'POST /api/newsletter/campaigns',
      'PATCH /api/newsletter/campaigns/1',
      'PUT /api/newsletter/settings',
      'PUT /api/newsletter/settings/smtp-password',
      'POST /api/newsletter/campaigns/1/cards/refresh',
      'GET /api/newsletter/campaigns/1',
    ]);
  });

  it('posts the revision a refresh read, and the unsaved preview body', async () => {
    const { api } = await load({ csrf_token: 'tok' });
    const fetchMock = stubFetch(ok);
    await api.refreshCard(7, 'blk', 3);
    await api.previewUnsaved({ subject: 's', preheader: '', body: [] });
    await api.testSend(7, ['a@x.org']);
    const bodies = fetchMock.mock.calls.map((c) => [
      c[0],
      JSON.parse((c[1] as RequestInit).body as string),
    ]);
    expect(bodies).toEqual([
      ['/api/newsletter/campaigns/7/cards/refresh', { block_id: 'blk', expected_revision: 3 }],
      ['/api/newsletter/preview', { subject: 's', preheader: '', body: [] }],
      ['/api/newsletter/campaigns/7/test-send', { recipients: ['a@x.org'] }],
    ]);
  });

  it('builds list and search queries, dropping empty values', async () => {
    const { api } = await load({});
    const fetchMock = stubFetch(() => new Response('[]', { status: 200 }));
    await api.listCampaigns({ q: 'spring', status: '', offset: 50 });
    await api.searchCards('article', 'a b');
    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual([
      '/api/newsletter/campaigns?q=spring&offset=50',
      '/api/newsletter/cards/articles?q=a+b',
    ]);
  });

  it('answers undefined for a 204 delete', async () => {
    const { api } = await load({ csrf_token: 'tok' });
    stubFetch(() => new Response(null, { status: 204 }));
    await expect(api.deleteCampaign(1)).resolves.toBeUndefined();
  });
});

describe('maps error codes to catalogue keys', () => {
  const t: Translate = (key) => `T(${key})`;

  it('translates the server code, never the English detail', async () => {
    const { api, http } = await load({ csrf_token: 'tok' });
    stubFetch(
      () => new Response(JSON.stringify({ detail: 'raw english', code: 'stale' }), { status: 409 }),
    );
    const error = await api.getCampaign(1).catch((e: unknown) => e);
    expect(http.isHttpStatus(error, 409)).toBe(true);
    expect(http.isCode(error, 'stale')).toBe(true);
    expect(http.errorMessage(error, t)).toBe('T(newsletter.errors.stale)');
  });

  it('falls back to generic for an unknown code, a framework 422 and a non-HTTP error', async () => {
    const { api, http } = await load({ csrf_token: 'tok' });
    stubFetch(() => new Response(JSON.stringify({ detail: 'x', code: 'weird' }), { status: 400 }));
    expect(http.errorMessage(await api.getCampaign(1).catch((e: unknown) => e), t)).toBe(
      'T(newsletter.errors.generic)',
    );
    stubFetch(
      () => new Response(JSON.stringify({ detail: [{ type: 'missing' }] }), { status: 422 }),
    );
    expect(http.errorMessage(await api.getCampaign(1).catch((e: unknown) => e), t)).toBe(
      'T(newsletter.errors.generic)',
    );
    expect(http.errorMessage(new TypeError('x'), t)).toBe('T(newsletter.errors.generic)');
  });

  it('names the known invalid_campaign fields, and is generic for any other detail', async () => {
    const { http } = await load({});
    const refusal = (detail: string) => new http.HttpError(detail, 422, 'invalid_campaign');
    const field = 'newsletter.errors_field';
    expect(http.errorMessage(refusal('subject: required'), t)).toBe(`T(${field}.subject_required)`);
    for (const detail of ['scheduled_at: out of range', 'at: out of range']) {
      expect(http.errorMessage(refusal(detail), t)).toBe(`T(${field}.schedule_out_of_range)`);
    }
    expect(http.errorMessage(refusal('name: too long'), t)).toBe(
      'T(newsletter.errors.invalid_campaign)',
    );
    // The detail is only a lookup key for invalid_campaign, never for another code.
    expect(http.errorMessage(new http.HttpError('subject: required', 409, 'stale'), t)).toBe(
      'T(newsletter.errors.stale)',
    );
  });

  it('does not let a code name an inherited property', async () => {
    const { http } = await load({});
    const error = new http.HttpError('x', 400, 'constructor');
    expect(http.errorMessage(error, t)).toBe('T(newsletter.errors.generic)');
  });

  it('names a CSRF refusal', async () => {
    const { api, http } = await load({ csrf_token: 'tok' });
    stubFetch(
      () =>
        new Response(JSON.stringify({ detail: 'CSRF token missing or invalid' }), { status: 403 }),
    );
    const error = await api
      .createCampaign({ name: 'n', list_type_key: 'l' })
      .catch((e: unknown) => e);
    expect(http.errorMessage(error, t)).toBe('T(newsletter.errors.csrf_failed)');
  });
});

// Mirrors `sm_newsletter/core/errors.py`: add a code there, add it here and to both catalogues.
const SERVER_CODES = [
  'audience_unsupported',
  'block_not_found',
  'campaign_cancelled',
  'card_source_gone',
  'dispatch_busy',
  'forbidden',
  'integration_unavailable',
  'invalid_body',
  'invalid_campaign',
  'invalid_password',
  'invalid_settings',
  'list_forbidden',
  'not_a_draft',
  'not_found',
  'public_base_url_required',
  'send_budget_exhausted',
  'sender_not_configured',
  'smtp_password_unreadable',
  'stale',
  'transport_unavailable',
  'unknown_list',
  'tenant_required',
];

describe('the error catalogue', () => {
  it.each(SERVER_CODES)('has an English line for %s', (code) => {
    expect((en.errors as Record<string, string>)[code]).toBeTruthy();
  });

  it('has a generic line', () => {
    expect(en.errors.generic).toBeTruthy();
  });
});

describe('sending calls', () => {
  it('hit the right path, method and body', async () => {
    const { api } = await load({ csrf_token: 'tok' });
    const fetchMock = stubFetch(ok);
    const signal = new AbortController().signal;
    await api.sendCampaign(4, { expected_revision: 3, scheduled_at: null });
    await api.sendCampaign(4, { expected_revision: 3, scheduled_at: '2030-01-01T10:00:00Z' });
    await api.unscheduleCampaign(4, 5);
    await api.pauseCampaign(4);
    await api.resumeCampaign(4);
    await api.cancelCampaign(4);
    await api.progress(4, signal);
    await api.estimate(4, null);
    await api.estimate(4, '2030-01-01T10:00:00Z');
    const sent = fetchMock.mock.calls.map((c) => ({
      call: `${(c[1] as RequestInit).method ?? 'GET'} ${c[0] as string}`,
      body: (c[1] as RequestInit).body,
    }));
    const base = '/api/newsletter/campaigns/4';
    expect(sent.map((s) => s.call)).toEqual([
      `POST ${base}/send`,
      `POST ${base}/send`,
      `POST ${base}/unschedule`,
      `POST ${base}/pause`,
      `POST ${base}/resume`,
      `POST ${base}/cancel`,
      `GET ${base}/progress`,
      `GET ${base}/estimate`,
      `GET ${base}/estimate?at=2030-01-01T10%3A00%3A00Z`,
    ]);
    expect(sent[0].body).toBe(JSON.stringify({ expected_revision: 3, scheduled_at: null }));
    expect(sent[1].body).toBe(
      JSON.stringify({ expected_revision: 3, scheduled_at: '2030-01-01T10:00:00Z' }),
    );
    expect(sent[2].body).toBe(JSON.stringify({ expected_revision: 5 }));
    expect(sent.slice(3, 6).map((s) => s.body)).toEqual([undefined, undefined, undefined]);
    expect((fetchMock.mock.calls[6][1] as RequestInit).signal).toBe(signal);
  });
});
