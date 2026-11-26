// @vitest-environment happy-dom
import type { Data } from '@puckeditor/core';
import * as React from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import LayoutEditor from '../../pages/LayoutEditor';
import { getLayout, type LayoutDetail } from '../utils/api';

const inertia = vi.hoisted(() => ({ visit: vi.fn(), reload: vi.fn() }));
let props: { layout: LayoutDetail; revisions: object[] };
vi.mock('@inertiajs/react', () => ({
  Head: () => null,
  router: inertia,
  usePage: () => ({ props }),
}));
vi.mock('@simple-module-py/ui/components/BrandingHead', () => ({ BrandingHead: () => null }));
// Like the real canvas, this keeps internal state until a remount.
vi.mock('@puckeditor/core', () => ({
  Puck: ({ data, onChange }: { data: Data; onChange: (data: Data) => void }) => {
    const [canvas, setCanvas] = React.useState(data);
    return (
      <button
        type="button"
        data-testid="canvas"
        onClick={() => {
          const next = { ...canvas, root: { props: { title: 'Local edit' } } };
          setCanvas(next);
          onChange(next);
        }}
      >
        {JSON.stringify(canvas)}
      </button>
    );
  },
}));

(globalThis as unknown as { React: unknown }).React = React;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root;
let server: LayoutDetail;
let writes: Record<string, unknown>[];
let generation: number;

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}
function doc(title: string) {
  return { content: [], root: { props: { title } } };
}
async function click(text: string) {
  const button = [...host.querySelectorAll('button')].find((el) => el.textContent === text);
  expect(button, text).toBeDefined();
  await act(async () => button?.click());
}
async function editSlots() {
  await act(async () => {
    for (const canvas of host.querySelectorAll<HTMLButtonElement>('[data-testid="canvas"]')) {
      canvas.click();
    }
  });
}
function externalEdit() {
  server = {
    ...server,
    header_data: doc('Server header'),
    footer_data: doc('Server footer'),
    updated_at: '2026-01-01T00:00:05Z',
  };
}
function banner() {
  return host.querySelector('[role="alert"]');
}

beforeEach(async () => {
  writes = [];
  generation = 0;
  server = {
    id: 1,
    header_data: doc('Original header'),
    footer_data: doc('Original footer'),
    created_at: '2026-01-01T00:00:00Z',
    updated_at: null,
  };
  props = {
    layout: structuredClone(server),
    revisions: [{ id: 3, created_at: server.created_at, note: null, created_by: null }],
  };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (!init?.method) return json(server);
      const body = JSON.parse(String(init.body ?? '{}'));
      writes.push(body);
      if ('expected_updated_at' in body && body.expected_updated_at !== server.updated_at) {
        return json({ detail: 'Server wording', code: 'layout_conflict' }, 409);
      }
      const { expected_updated_at: _token, ...patch } = body;
      server = {
        ...server,
        ...(url.endsWith('/restore')
          ? { header_data: doc('Restored header'), footer_data: doc('Restored footer') }
          : patch),
        updated_at: '2026-01-01T00:00:10Z',
      };
      return json(server);
    }),
  );
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  inertia.visit.mockImplementation(async (_url, options) => {
    props = { ...props, layout: await getLayout() };
    if (options?.preserveState === false) generation++;
    root.render(<LayoutEditor key={generation} />);
  });
  await act(async () => root.render(<LayoutEditor key={generation} />));
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

it('refuses a stale save, preserves edits, and Reload resets both canvases and the token', async () => {
  await editSlots();
  externalEdit();
  await click('Save layout');
  expect(banner()?.textContent).toContain('This layout was changed elsewhere');
  expect(host.textContent).not.toContain('Layout saved');
  expect(host.querySelectorAll('[data-testid="canvas"]')[0].textContent).toContain('Local edit');
  expect(server.header_data).toEqual(doc('Server header'));
  expect(writes[0].expected_updated_at).toBeNull();
  await click('Reload');
  expect(inertia.visit).toHaveBeenCalledWith('/pagebuilder/layout', { preserveState: false });
  expect(banner()).toBeNull();
  const canvases = host.querySelectorAll('[data-testid="canvas"]');
  expect(canvases[0].textContent).toContain('Server header');
  expect(canvases[1].textContent).toContain('Server footer');
  await editSlots();
  await click('Save layout');
  expect(writes.at(-1)?.expected_updated_at).toBe('2026-01-01T00:00:05Z');
  expect(host.textContent).toContain('Layout saved');
});

it('Overwrite deliberately saves both local slots and subsequent saves use its returned token', async () => {
  await editSlots();
  externalEdit();
  await click('Save layout');
  expect(banner()).not.toBeNull();
  await click('Overwrite');
  expect(writes.at(-1)).not.toHaveProperty('expected_updated_at');
  expect(server.header_data).toEqual(doc('Local edit'));
  expect(server.footer_data).toEqual(doc('Local edit'));
  expect(banner()).toBeNull();
  expect(host.textContent).toContain('Layout saved');
  await click('Save layout');
  expect(writes.at(-1)?.expected_updated_at).toBe('2026-01-01T00:00:10Z');
});

it('each successful ordinary save advances the screen token', async () => {
  await editSlots();
  await click('Save layout');
  expect(writes[0].expected_updated_at).toBeNull();
  await click('Save layout');
  expect(writes[1].expected_updated_at).toBe('2026-01-01T00:00:10Z');
  expect(banner()).toBeNull();
});

it('a stale revision Restore shows the same conflict without claiming success', async () => {
  externalEdit();
  await click('History (1)');
  await click('Restore');
  const dialog = document.querySelector('[role="alertdialog"]');
  expect(dialog).not.toBeNull();
  const confirm = [...(dialog?.querySelectorAll('button') ?? [])].find(
    (button) => button.textContent === 'Restore',
  );
  await act(async () => confirm?.click());
  expect(writes[0].expected_updated_at).toBeNull();
  expect(banner()?.textContent).toContain('This layout was changed elsewhere');
  expect(host.textContent).not.toContain('Revision restored');
  expect(server.header_data).toEqual(doc('Server header'));
  expect(document.querySelector('[role="alertdialog"]')).toBeNull();
});

it('Overwrite after a refused Restore repeats the restore, not a save of the screen', async () => {
  externalEdit();
  await click('History (1)');
  await click('Restore');
  const dialog = document.querySelector('[role="alertdialog"]');
  const confirm = [...(dialog?.querySelectorAll('button') ?? [])].find(
    (button) => button.textContent === 'Restore',
  );
  await act(async () => confirm?.click());
  expect(banner()).not.toBeNull();
  await click('Overwrite');
  // The retry is the restore without a token (no slots in its body), and the screen adopts it.
  expect(writes[1]).not.toHaveProperty('expected_updated_at');
  expect(writes[1]).not.toHaveProperty('header_data');
  expect(server.header_data).toEqual(doc('Restored header'));
  expect(banner()).toBeNull();
  expect(host.textContent).toContain('Revision restored');
  await click('Save layout');
  expect(writes[2].expected_updated_at).toBe('2026-01-01T00:00:10Z');
  expect(writes[2].header_data).toEqual(doc('Restored header'));
});

it('a successful Restore advances the token used when saving both restored slots', async () => {
  await click('History (1)');
  await click('Restore');
  const dialog = document.querySelector('[role="alertdialog"]');
  const confirm = [...(dialog?.querySelectorAll('button') ?? [])].find(
    (button) => button.textContent === 'Restore',
  );
  expect(confirm).toBeDefined();
  await act(async () => confirm?.click());
  expect(writes[0].expected_updated_at).toBeNull();
  await click('Save layout');
  expect(writes[1].expected_updated_at).toBe('2026-01-01T00:00:10Z');
  expect(writes[1].header_data).toEqual(doc('Restored header'));
  expect(writes[1].footer_data).toEqual(doc('Restored footer'));
  expect(banner()).toBeNull();
});

it('a failed Overwrite leaves the conflict and local edits available for another attempt', async () => {
  await editSlots();
  externalEdit();
  await click('Save layout');
  vi.mocked(fetch).mockImplementationOnce(async () => json({ detail: 'Unavailable' }, 503));
  await click('Overwrite');
  expect(banner()).not.toBeNull();
  expect(host.textContent).toContain('Unavailable');
  expect(host.textContent).not.toContain('Layout saved');
  await click('Overwrite');
  expect(server.header_data).toEqual(doc('Local edit'));
  expect(banner()).toBeNull();
});
