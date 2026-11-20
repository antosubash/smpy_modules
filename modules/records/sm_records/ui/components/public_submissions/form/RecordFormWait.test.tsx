// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { act, mount, settle } from '../../../page-tests/test-dom';
import { definition, fill, send, server } from './record-form-test-support';

vi.mock('@simple-module-py/pagebuilder', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  Section: ({ children }: { children: unknown }) => <section>{children as never}</section>,
}));
vi.mock('./CaptchaWidget', () => ({ CaptchaWidget: () => null }));
const { RecordFormRender } = await import('./RecordFormRender');

const block = () => (
  <RecordFormRender
    id="RecordForm-abc"
    typeKey="contact"
    title=""
    intro=""
    submitLabel=""
    successTitle=""
    successBody=""
    labels={[]}
    kindHint=""
  />
);

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('waiting', () => {
  it('says a 429 in minutes, rounded up', async () => {
    for (const [seconds, words] of [
      ['90', 'wait about 2 minutes'],
      ['30', 'wait about 1 minute'],
      ['600', 'wait about 10 minutes'],
    ] as const) {
      server(
        { status: 200, body: definition() },
        { status: 429, body: { code: 'rate_limited' }, headers: { 'Retry-After': seconds } },
      );
      const view = await mount(block());
      await settle();
      await fill(view);
      await send(view);
      expect(view.find('[role="alert"]')?.textContent).toContain(words);
      await view.unmount();
    }
  });

  it('sends only once the form is old enough, so a quick submit is one request, not a refusal and a retry', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'Date'] });
    const calls = server(
      { status: 200, body: definition({ min_fill_seconds: 3 }) },
      { status: 202, body: { ok: true } },
    );
    const view = await mount(block());
    await settle();
    await fill(view);
    await send(view); // clicked at once
    expect(calls.map((c) => c.init?.method ?? 'GET')).toEqual(['GET']); // nothing sent yet
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_400);
    });
    await settle();
    expect(calls.map((c) => c.init?.method ?? 'GET')).toEqual(['GET', 'POST']); // one send, no 400
    expect(view.find('[data-testid="records-form-success"]')).not.toBeNull();
    await view.unmount();
  });
});
