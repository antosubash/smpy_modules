// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { click, mount, settle } from '../test-dom';

vi.mock('@inertiajs/react', () => ({ Head: () => null }));
vi.mock('@simple-module-py/ui/components/BrandingHead', () => ({ BrandingHead: () => null }));

const SubmissionAction = (await import('../pages/SubmissionAction')).default;

const COPY = {
  title: 'Abonnement bestätigen',
  intro: 'Klicken Sie auf die Schaltfläche.',
  button: 'Abonnement bestätigen',
  done: 'Bestätigt.',
  already: 'Bereits bestätigt.',
  expired: 'Abgelaufen.',
  sending: 'Einen Moment …',
  failed: 'Fehlgeschlagen.',
};

function answer(status: number, body: unknown) {
  return vi.fn(async () => new Response(JSON.stringify(body), { status }));
}

function page(token = 'tok') {
  return (
    <SubmissionAction
      action="confirm"
      token={token}
      locale="de"
      endpoint="/api/records/submissions/confirm"
      copy={COPY}
    />
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('SubmissionAction', () => {
  it('changes nothing until the button is pressed, then posts the token', async () => {
    const fetch = answer(200, { status: 'confirmed' });
    vi.stubGlobal('fetch', fetch);
    const view = await mount(page());
    expect(fetch).not.toHaveBeenCalled();
    expect(view.find('main')?.getAttribute('lang')).toBe('de');
    await click(view.button('Abonnement bestätigen'));
    await settle();
    expect(fetch).toHaveBeenCalledWith(
      '/api/records/submissions/confirm',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ t: 'tok' }) }),
    );
    expect(view.find('[data-testid="submission-action-result"]')?.textContent).toBe('Bestätigt.');
    await view.unmount();
  });

  it('says already confirmed, expired, or that it failed', async () => {
    for (const [status, body, text] of [
      [200, { status: 'already_confirmed' }, 'Bereits bestätigt.'],
      [410, { code: 'link_expired' }, 'Abgelaufen.'],
    ] as const) {
      vi.stubGlobal('fetch', answer(status, body));
      const view = await mount(page());
      await click(view.button('Abonnement bestätigen'));
      await settle();
      expect(view.find('[data-testid="submission-action-result"]')?.textContent).toBe(text);
      await view.unmount();
    }
    vi.stubGlobal('fetch', answer(500, {}));
    const view = await mount(page());
    await click(view.button('Abonnement bestätigen'));
    await settle();
    expect(view.find('[role="alert"]')?.textContent).toBe('Fehlgeschlagen.');
    // ...and the button is still there to try again.
    expect(view.button('Abonnement bestätigen')).toBeDefined();
    await view.unmount();
  });
});
