// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, expect, it } from 'vitest';
import type { Property } from '../utils/types';
import { PropertySettings } from './PropertySettings';

(globalThis as unknown as { React: unknown }).React = React;
(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
afterEach(async () => {
  await act(async () => root?.unmount());
  document.body.innerHTML = '';
});
const property: Property = {
  id: 'property-1',
  name: 'Website',
  kind: 'public',
  origins: ['https://example.com'],
  route_patterns: ['/guide'],
  event_allowlist: {},
  utm_parameters: [],
  enabled: true,
};
const button = (name: string) =>
  Array.from(document.querySelectorAll('button')).find(
    (item) => item.textContent === name,
  ) as HTMLButtonElement;
async function mount(
  canManage: boolean,
  selected: Property | undefined,
  onDelete = async () => {},
  onSave = async () => {},
) {
  const container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
  await act(async () =>
    root.render(
      <PropertySettings
        canManage={canManage}
        property={selected}
        geo={null}
        onSave={onSave}
        onDelete={onDelete}
      />,
    ),
  );
}
it('view-only users have no management actions', async () => {
  await mount(false, property);
  expect(document.querySelector('button')).toBeNull();
});
it('opens setup secondarily and keeps delete behind confirmation', async () => {
  let deleted = 0;
  await mount(true, property, async () => {
    deleted++;
  });
  expect(document.body.textContent).not.toContain('Tracking setup');
  await act(async () => button('Manage property').click());
  expect(document.body.textContent).toContain('Tracking setup');
  await act(async () => button('Delete property').click());
  expect(deleted).toBe(0);
  expect(document.querySelector('[role="alertdialog"]')).not.toBeNull();
  await act(async () => button('Cancel').click());
  expect(deleted).toBe(0);
  expect(document.querySelector('[role="alertdialog"]')).toBeNull();
});
it('the empty property action opens creation directly', async () => {
  await mount(true, undefined);
  await act(async () => button('New property').click());
  expect(document.querySelector('form')).not.toBeNull();
  expect(document.body.textContent).toContain('Enable tracking');
});

it('a failed save leaves the real editor open with the API error', async () => {
  await mount(
    true,
    property,
    async () => {},
    async () => {
      throw new Error('Save unavailable');
    },
  );
  await act(async () => button('Manage property').click());
  await act(async () => button('Edit').click());
  await act(async () =>
    document
      .querySelector('form')
      ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })),
  );
  expect(document.querySelector('[role="alert"]')?.textContent).toBe('Save unavailable');
  expect(document.querySelector('form')).not.toBeNull();
  expect(button('Close').disabled).toBe(false);
});
