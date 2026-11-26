// @vitest-environment happy-dom
import { expect, it } from 'vitest';
import {
  click,
  edit,
  externalEdit,
  host,
  server,
  tick,
  title,
  visitMock,
  writes,
} from './pageEditor-test-support';

it('Reload discards local edits across toolbar, SEO, settings and Puck canvas', async () => {
  await click('Settings');
  const localTitle = title();
  await edit(localTitle, 'Local title');
  await click('SEO');
  const seo = [...host.querySelectorAll<HTMLInputElement>('input')].find(
    (el) => el.value === 'Original SEO',
  );
  if (!seo) throw new Error('Missing SEO input');
  await edit(seo, 'Local SEO');
  externalEdit();
  await tick();
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    'This page was changed elsewhere',
  );
  expect(writes).toHaveLength(1);
  await click('Reload');
  expect(visitMock()).toHaveBeenCalledWith('/pagebuilder/7/edit', { preserveState: false });
  expect(title().value).toBe('Server title');
  expect(host.querySelector('[role="alert"]')).toBeNull();
  expect(host.querySelector('[data-testid="canvas"]')?.textContent).toContain('Server canvas');
  await click('Settings');
  const nav = host.querySelector('[role="checkbox"]');
  expect(nav?.getAttribute('aria-checked')).toBe('true');
  await click('SEO');
  expect([...host.querySelectorAll('input')].some((el) => el.value === 'Server SEO')).toBe(true);
  await tick();
  expect(writes).toHaveLength(1); // Reload establishes a clean baseline.
  await edit(title(), 'After reload');
  await tick();
  expect(writes.at(-1)?.expected_updated_at).toBe('2026-01-01T00:00:05Z');
  expect(server.title).toBe('After reload');
});

it('Overwrite is explicit and autosave remains paused until its button is clicked', async () => {
  externalEdit();
  await edit(title(), 'Keep my title');
  await tick();
  expect(host.querySelector('[role="alert"]')).not.toBeNull();
  await edit(title(), 'Keep my latest title');
  await tick();
  await tick();
  expect(writes).toHaveLength(1);
  expect(server.title).toBe('Server title');
  await click('Overwrite');
  expect(writes.at(-1)).not.toHaveProperty('expected_updated_at');
  expect(server.title).toBe('Keep my latest title');
  expect(host.querySelector('[role="alert"]')).toBeNull();
  await edit(title(), 'Resumed');
  await tick();
  expect(writes.at(-1)?.expected_updated_at).toBe('2026-01-01T00:00:10Z');
});
