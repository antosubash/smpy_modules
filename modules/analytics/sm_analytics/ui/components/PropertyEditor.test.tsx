// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { saveProperty } from '../utils/api';
import { PropertyEditor } from './PropertyEditor';

(globalThis as unknown as { React: unknown }).React = React;
(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
afterEach(async () => {
  await act(async () => root?.unmount());
  document.body.replaceChildren();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it('places each server validation error next to its field and focuses the first invalid field', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      Response.json(
        {
          detail: [
            {
              loc: ['body', 'origins', 0],
              msg: 'Value error, Expected an exact http(s) origin without a path',
              type: 'value_error',
            },
            {
              loc: ['body', 'route_patterns'],
              msg: 'Value error, Route patterns must start with /',
              type: 'value_error',
            },
          ],
        },
        { status: 422 },
      ),
    ),
  );
  const container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
  await act(async () =>
    root.render(
      <PropertyEditor
        onSave={async (input) => {
          await saveProperty(input);
        }}
        onCancel={() => {}}
      />,
    ),
  );
  await act(async () =>
    container
      .querySelector('form')
      ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })),
  );
  const origins = container.querySelector('textarea[id$="-origins"]');
  const routes = container.querySelector('textarea[id$="-routes"]');
  for (const [field, message] of [
    [origins, 'origin'],
    [routes, 'start with /'],
  ] as const) {
    expect(field?.getAttribute('aria-invalid')).toBe('true');
    const descriptions = field
      ?.getAttribute('aria-describedby')
      ?.split(' ')
      .map((id) => document.getElementById(id)?.textContent)
      .join(' ');
    expect(descriptions).toContain(message);
  }
  expect(document.activeElement).toBe(origins);
  expect(container.textContent).not.toContain('Value error,');
});
it('brings a non-field save failure into view', async () => {
  const scroll = vi.spyOn(HTMLElement.prototype, 'scrollIntoView');
  const container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
  await act(async () =>
    root.render(
      <PropertyEditor
        onSave={async () => {
          throw new Error('Save unavailable');
        }}
        onCancel={() => {}}
      />,
    ),
  );
  await act(async () =>
    container
      .querySelector('form')
      ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })),
  );
  expect(container.querySelector('[role="alert"]')?.textContent).toBe('Save unavailable');
  expect(scroll).toHaveBeenCalled();
});
