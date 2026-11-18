// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { REASON_CODES } from '../utils/api-import';
import { baseProps, choose, IMPORTS, icsFile, importOut, item, page } from './import-support';
import { flush, stubFetch } from './support';
import { act, click, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));

const { default: Import } = await import('../../pages/Import');

const field = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const text = () => document.body.textContent ?? '';
const button = (label: string) =>
  [...document.querySelectorAll('button')].find((b) => b.textContent?.includes(label));

beforeEach(() => {
  window.history.replaceState(null, '', '/admin/events/import');
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});

async function upload(view: Awaited<ReturnType<typeof mount>>, file = icsFile()) {
  await setValue(field<HTMLSelectElement>('events-import-calendar'), 'c1');
  await choose(field<HTMLInputElement>('events-import-file'), file);
  await click(button('Upload and preview'));
  await flush(50);
  return view;
}

describe('Import screen', () => {
  it('uploads, then shows the preview: counts, rows in their own zone, what was dropped', async () => {
    const calls = stubFetch({
      [`POST ${IMPORTS}`]: () =>
        Response.json(
          importOut({
            status: 'staged',
            dropped: { ATTENDEE: 3, VALARM: 1 },
            reasons: { floating_time: 1 },
          }),
          { status: 202 },
        ),
      [`GET ${IMPORTS}/7`]: importOut({ dropped: { ATTENDEE: 3, VALARM: 1 } }),
      [`GET ${IMPORTS}/7/items`]: page([
        item(1, { notes: ['floating_time'] }),
        item(2, { verdict: 'update', title: 'Old talk' }),
        item(3, {
          verdict: 'skip',
          reason: 'unsupported_rule',
          title: 'Bad rule',
          starts_at: null,
          local_start: null,
        }),
      ]),
    });
    const view = await upload(await mount(<Import {...baseProps} />));
    const post = calls.find((c) => c.method === 'POST');
    expect(post?.url).toBe(IMPORTS);
    expect(window.location.search).toBe('?id=7'); // a reload resumes
    expect(text()).toContain('Preview');
    for (const title of ['Talk 1', 'Old talk', 'Bad rule']) expect(text()).toContain(title);
    expect(text()).toContain('2026-07-01 10:00');
    expect(text()).toContain('Europe/Vienna');
    expect(text()).toContain('This rule is not supported');
    expect(text()).toContain('Not imported');
    expect(text()).toContain('3');
    expect(text()).toContain('attendees');
    expect(text()).toContain('alarms');
    await view.unmount();
  });

  it('refuses a file over the cap before anything is sent', async () => {
    const calls = stubFetch({});
    const view = await mount(<Import {...baseProps} max_bytes={1024 * 1024} />);
    await setValue(field<HTMLSelectElement>('events-import-calendar'), 'c1');
    await choose(field<HTMLInputElement>('events-import-file'), icsFile(2 * 1024 * 1024));
    await click(button('Upload and preview'));
    expect(text()).toContain('larger than 1 MB');
    expect(calls).toHaveLength(0);
    await view.unmount();
  });

  it('offers publishing only with the permission', async () => {
    const routes = {
      [`GET ${IMPORTS}/7`]: importOut(),
      [`GET ${IMPORTS}/7/items`]: page([item(1)]),
    };
    stubFetch(routes);
    const plain = await mount(<Import {...baseProps} import_id={7} />);
    await flush(50);
    expect(button('Import as drafts')).toBeDefined();
    expect(button('Import and publish')).toBeUndefined();
    expect(text()).toContain('published events are updated only if you may publish');
    await plain.unmount();
    document.body.innerHTML = '';
    stubFetch(routes);
    const publisher = await mount(<Import {...baseProps} can_publish import_id={7} />);
    await flush(50);
    expect(button('Import and publish')).toBeDefined();
    await publisher.unmount();
  });

  it('applies, polls until done and shows the result', async () => {
    let reads = 0;
    const calls = stubFetch({
      [`GET ${IMPORTS}/7`]: () => {
        reads += 1;
        if (reads === 1) return importOut();
        if (reads === 2) return importOut({ status: 'running', processed: 1, total: 3 });
        return importOut({
          status: 'done',
          created: 2,
          updated: 1,
          processed: 3,
          finished_at: 'x',
        });
      },
      [`GET ${IMPORTS}/7/items`]: (call: { url: string }) =>
        call.url.includes('outcome=')
          ? page([item(1, { outcome: 'created', event_id: 'e1' })])
          : page([item(1, { outcome: 'created', event_id: 'e1' })]),
      [`POST ${IMPORTS}/7/apply`]: () =>
        Response.json(importOut({ status: 'queued' }), { status: 202 }),
    });
    vi.useFakeTimers();
    const view = await mount(<Import {...baseProps} import_id={7} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    await click(button('Import as drafts'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ publish: false });
    expect(text()).toMatch(/Importing|Waiting/);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(text()).toContain('Result');
    expect(text()).toContain('Created 2');
    expect(text()).toContain('Updated 1');
    expect(document.querySelector('a[href="/admin/events/edit/e1"]')).not.toBeNull();
    await view.unmount();
  });

  it('shows a failed import as its code, and Start again discards it', async () => {
    const calls = stubFetch({
      [`GET ${IMPORTS}/7`]: importOut({ status: 'failed', error_code: 'too_many_events' }),
      [`DELETE ${IMPORTS}/7`]: null,
    });
    const view = await mount(<Import {...baseProps} import_id={7} />);
    await flush(50);
    expect(text()).toContain('more events than one import takes');
    expect(text()).not.toContain('too_many_events');
    await click(button('Start again'));
    await flush(50);
    expect(calls.some((c) => c.method === 'DELETE')).toBe(true);
    expect(field('events-import-file')).not.toBeNull();
    expect(window.location.search).toBe('');
    await view.unmount();
  });

  it('resumes polling from ?id= after a reload', async () => {
    let reads = 0;
    stubFetch({
      [`GET ${IMPORTS}/9`]: () =>
        ++reads < 3
          ? importOut({ id: 9, status: 'running', total: 4, processed: reads })
          : importOut({ id: 9, status: 'done', created: 4, processed: 4 }),
      [`GET ${IMPORTS}/9/items`]: page([item(1, { outcome: 'created', event_id: 'e1' })]),
    });
    vi.useFakeTimers();
    const view = await mount(<Import {...baseProps} import_id={9} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    expect(text()).toContain('Importing');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(text()).toContain('Created 4');
    await view.unmount();
  });

  it('stops polling when the page goes away', async () => {
    const calls = stubFetch({ [`GET ${IMPORTS}/7`]: importOut({ status: 'running' }) });
    vi.useFakeTimers();
    const view = await mount(<Import {...baseProps} import_id={7} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500);
    });
    const before = calls.length;
    expect(before).toBeGreaterThan(1);
    await view.unmount();
    await vi.advanceTimersByTimeAsync(5000);
    expect(calls.length).toBe(before);
  });

  it('renders everything from the file as text', async () => {
    const hostile = '<img src=x onerror="window.__pwned=1"><script>window.__pwned=1</script>';
    stubFetch({
      [`GET ${IMPORTS}/7`]: importOut(),
      [`GET ${IMPORTS}/7/items`]: page([item(1, { title: hostile })]),
    });
    const view = await mount(<Import {...baseProps} import_id={7} />);
    await flush(50);
    expect(text()).toContain('<img src=x onerror=');
    expect(document.querySelector('img[src="x"]')).toBeNull();
    expect(document.querySelectorAll('script').length).toBe(0);
    expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
    await view.unmount();
  });

  it('lists only the calendars the server sent, and says so when there are none', async () => {
    stubFetch({});
    const view = await mount(<Import {...baseProps} />);
    const options = [...field<HTMLSelectElement>('events-import-calendar').options].map(
      (o) => o.text,
    );
    expect(options).toEqual(expect.arrayContaining(['Team', 'Office']));
    await view.unmount();
    document.body.innerHTML = '';
    const none = await mount(<Import {...baseProps} calendars={[]} />);
    expect(text()).toContain('You cannot write events in any calendar yet');
    expect(button('Upload and preview')?.hasAttribute('disabled') ?? true).toBe(true);
    await none.unmount();
  });

  it('shows the server’s refusal of an upload in words', async () => {
    stubFetch({
      [`POST ${IMPORTS}`]: () =>
        Response.json({ detail: 'x', code: 'import_busy' }, { status: 409 }),
    });
    const view = await upload(await mount(<Import {...baseProps} />));
    expect(text()).toContain('Too many imports');
    await view.unmount();
  });

  it('shows the filed reasons of a skipped item and the locked-target reason', async () => {
    stubFetch({
      [`GET ${IMPORTS}/7`]: importOut({ status: 'done', skipped: 1, processed: 1 }),
      [`GET ${IMPORTS}/7/items`]: page([
        item(1, { verdict: 'update', outcome: 'skipped', outcome_code: 'publish_required' }),
      ]),
    });
    const view = await mount(<Import {...baseProps} import_id={7} />);
    await flush(50);
    expect(text()).toContain('needs the publish permission');
    await view.unmount();
  });
});

describe('labels', () => {
  it('every reason code has a label in words', async () => {
    const { reasonText } = await import('../utils/api-import');
    for (const code of REASON_CODES) {
      const label = reasonText(code);
      expect(label, code).not.toBe(code);
      expect(label.length, code).toBeGreaterThan(8);
    }
  });
});
