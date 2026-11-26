// @vitest-environment happy-dom
import { expect, it } from 'vitest';

import {
  click,
  edit,
  externalEdit,
  failNextWrite,
  host,
  server,
  tick,
  title,
  writes,
} from './pageEditor-test-support';

it.each([409, 503])('a refused schedule (%s) never changes the stored badge', async (status) => {
  await click('Settings');
  await click('SEO');
  const input = host.querySelector<HTMLInputElement>('[data-testid="schedule-publish-at"]');
  if (!input) throw new Error('Missing schedule input');
  await edit(input, '2099-01-01T09:00');
  expect(host.textContent).not.toContain('Scheduled to publish');
  failNextWrite(status, status === 409 ? 'page_conflict' : undefined);
  await click('Save schedule');
  expect(server.publish_at).toBeNull();
  expect(host.textContent).not.toContain('Scheduled to publish');
  expect(input.value).toBe('2099-01-01T09:00');
  if (status === 409) {
    expect(host.textContent?.match(/This page was changed elsewhere/g)).toHaveLength(1);
  }
});

it('shows a schedule badge only after accepting the server response', async () => {
  await click('Settings');
  await click('SEO');
  const input = host.querySelector<HTMLInputElement>('[data-testid="schedule-publish-at"]');
  if (!input) throw new Error('Missing schedule input');
  await edit(input, '2099-01-01T09:00');
  expect(host.textContent).not.toContain('Scheduled to publish');
  await click('Save schedule');
  expect(server.publish_at).not.toBeNull();
  expect(host.textContent).toContain('Scheduled to publish');
});

it('a deleted page replaces conflict choices and stops every later save', async () => {
  externalEdit();
  await edit(title(), 'My draft');
  await tick();
  failNextWrite(404, 'page_not_found');
  await click('Overwrite');
  expect(host.querySelector('[role="alert"]')?.textContent).toContain('deleted elsewhere');
  const buttons = [...host.querySelectorAll('button')].map((el) => el.textContent);
  expect(buttons).not.toContain('Overwrite');
  expect(buttons).not.toContain('Save draft');
  expect(buttons).not.toContain('Publish');
  expect(buttons).toContain('Reload');
  await click('Settings');
  expect(host.textContent).not.toContain('Save as template');
  const attempts = writes.length;
  await edit(title(), 'Still local');
  await tick();
  await tick();
  expect(writes).toHaveLength(attempts);
});

it('the conflict banner is the only toolbar conflict message', async () => {
  externalEdit();
  await edit(title(), 'My draft');
  await tick();
  expect(host.textContent?.match(/This page was changed elsewhere/g)).toHaveLength(1);
});

it('a stale publish explains the conflict inside the dialog and removes its submit action', async () => {
  externalEdit();
  await click('Publish');
  const dialog = document.querySelector('[role="dialog"]');
  if (!dialog) throw new Error('Missing publish dialog');
  const publish = [...dialog.querySelectorAll('button')].find((el) => el.type === 'submit');
  if (!publish) throw new Error('Missing publish submit');
  const { act } = await import('react');
  await act(async () => publish.click());
  expect(dialog.querySelector('[role="alert"]')?.textContent).toContain('changed elsewhere');
  expect(dialog.querySelector('button[type="submit"]')).toBeNull();
  const attempts = writes.length;
  await act(async () =>
    dialog
      .querySelector('form')
      ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })),
  );
  expect(writes).toHaveLength(attempts);
  const cancel = [...dialog.querySelectorAll('button')].find((el) => el.textContent === 'Cancel');
  await act(async () => cancel?.click());
  expect(host.querySelector('[role="alert"]')?.textContent).toContain('changed elsewhere');
});
