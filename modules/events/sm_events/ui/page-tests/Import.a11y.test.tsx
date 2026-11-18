// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { baseProps, choose, IMPORTS, icsFile, importOut, item, page } from './import-support';
import { flush, stubFetch } from './support';
import { click, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));

const { default: Import } = await import('../../pages/Import');

const field = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const button = (label: string) =>
  [...document.querySelectorAll('button')].find((b) => b.textContent?.includes(label));
const announced = () =>
  document.querySelector('[data-testid="events-import-announce"]')?.textContent;

beforeEach(() => window.history.replaceState(null, '', '/admin/events/import'));
afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});

async function upload() {
  await setValue(field<HTMLSelectElement>('events-import-calendar'), 'c1');
  await choose(field<HTMLInputElement>('events-import-file'), icsFile());
  await click(button('Upload and preview'));
  await flush(50);
}

describe('Import screen, focus and announcements', () => {
  it('moves focus to the preview heading and announces the counts', async () => {
    stubFetch({
      [`POST ${IMPORTS}`]: () => Response.json(importOut(), { status: 202 }),
      [`GET ${IMPORTS}/7`]: importOut(),
      [`GET ${IMPORTS}/7/items`]: page([item(1)]),
    });
    const view = await mount(<Import {...baseProps} />);
    expect(announced()).toBe('');
    await upload();
    expect(document.activeElement?.tagName).toBe('H2');
    expect(document.activeElement?.textContent).toBe('Preview');
    expect(announced()).toBe(
      'Preview ready: 3 events, 2 new, 1 to update, 0 unchanged, 0 skipped.',
    );
    await view.unmount();
  });

  it('announces the result and moves focus to its heading', async () => {
    stubFetch({
      [`POST ${IMPORTS}`]: () => Response.json(importOut(), { status: 202 }),
      [`GET ${IMPORTS}/7`]: importOut({ status: 'done', created: 2, unchanged: 1, processed: 3 }),
      [`POST ${IMPORTS}/7/apply`]: () =>
        Response.json(importOut({ status: 'done', created: 2, unchanged: 1 }), { status: 202 }),
      [`GET ${IMPORTS}/7/items`]: page([item(1)]),
    });
    const view = await mount(<Import {...baseProps} />);
    await upload();
    await click(button('Import as drafts'));
    await flush(50);
    expect(document.activeElement?.textContent).toBe('Result');
    expect(announced()).toBe(
      'Import finished: 2 created, 0 updated, 1 unchanged, 0 skipped, 0 failed.',
    );
    await view.unmount();
  });

  it('announces a refusal with its reason and focuses its heading', async () => {
    stubFetch({
      [`POST ${IMPORTS}`]: () =>
        Response.json(importOut({ status: 'failed', error_code: 'too_many_events' }), {
          status: 202,
        }),
      [`GET ${IMPORTS}/7`]: importOut({ status: 'failed', error_code: 'too_many_events' }),
    });
    const view = await mount(<Import {...baseProps} />);
    await upload();
    expect(document.activeElement?.textContent).toBe('The import failed');
    expect(announced()).toContain('more events than one import takes');
    await view.unmount();
  });

  it('lists the waiting imports when the cap is reached', async () => {
    stubFetch({
      [`POST ${IMPORTS}`]: () =>
        Response.json({ detail: 'busy', code: 'import_busy' }, { status: 409 }),
      [`GET ${IMPORTS}`]: {
        items: [importOut({ id: 4, filename: 'a.ics' }), importOut({ id: 5, status: 'done' })],
        total: 2,
      },
    });
    const view = await mount(<Import {...baseProps} />);
    await upload();
    expect(document.body.textContent).toContain('You have too many imports waiting');
    const links = [...document.querySelectorAll('a')].map((a) => a.getAttribute('href'));
    expect(links).toContain('/admin/events/import?id=4');
    expect(links).not.toContain('/admin/events/import?id=5'); // finished: nothing to deal with
    await view.unmount();
  });
});
