/**
 * A three-function DOM harness for the tests that have to *drive* a
 * component rather than read its first render.
 *
 * Most of this module's frontend tests are pure (`utils/`) or render once
 * through `react-dom/server`. A handful can't be: "a new field row keeps its
 * Key input editable once the key collides" (R1) and "Enter in the editor
 * saves" (R13) are both about what happens after an interaction, which
 * static markup cannot express. There is no `@testing-library/react` in this
 * repo, so this is the small amount of it those tests actually need — the
 * native-setter `input` dispatch included, because React's own value tracker
 * swallows a plain `el.value = x`.
 *
 * Not a test file itself (no `.test.` in the name), so vitest's `include`
 * leaves it alone; the files that import it opt into happy-dom with a
 * `@vitest-environment` comment of their own.
 */

import * as React from 'react';

// `@simple-module-py/ui` is published compiled against a global `React`, and
// happy-dom gives us no `window.React` — the same line the review's own
// reproduction file opens with.
(globalThis as unknown as { React: unknown }).React = React;
// Silences React 19's "not configured to support act(...)" and makes `act`
// flush effects synchronously.
(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

export type Mounted = {
  host: HTMLElement;
  root: Root;
  /** Render again — for a parent that owns the component's state. */
  render: (next: React.ReactElement) => Promise<void>;
  /** Inside `act`, so effect cleanups (a window listener, an interval) have
   *  actually run by the time the next test mounts. */
  unmount: () => Promise<void>;
  find: <T extends Element = HTMLElement>(selector: string) => T | null;
  all: <T extends Element = HTMLElement>(selector: string) => T[];
  /** The first button (or link) whose text contains `text`. */
  button: (text: string) => HTMLElement | undefined;
};

export async function mount(element: React.ReactElement): Promise<Mounted> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  const root = createRoot(host);
  const render = async (next: React.ReactElement) => {
    await act(async () => {
      root.render(next);
    });
  };
  await render(element);
  return {
    host,
    root,
    render,
    unmount: async () => {
      await act(async () => {
        root.unmount();
      });
      host.remove();
    },
    find: <T extends Element = HTMLElement>(selector: string) =>
      host.querySelector(selector) as T | null,
    all: <T extends Element = HTMLElement>(selector: string) =>
      Array.from(host.querySelectorAll(selector)) as T[],
    button: (text: string) =>
      Array.from(host.querySelectorAll('button, a')).find((el) =>
        (el.textContent ?? '').includes(text),
      ) as HTMLElement | undefined,
  };
}

/** Type into a React-controlled input: the value goes through the prototype
 *  setter so React's own tracker sees a change, then `input` bubbles to the
 *  root listener. */
export async function setValue(
  el: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement,
  value: string,
): Promise<void> {
  const proto =
    el instanceof HTMLSelectElement
      ? HTMLSelectElement.prototype
      : el instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype
        : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
  await act(async () => {
    setter?.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    if (el instanceof HTMLSelectElement) el.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

export async function click(el: Element | null | undefined): Promise<void> {
  await act(async () => {
    el?.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
  });
}

/** Press a key on `target` — `{ key: 'Enter' }` and friends. `window` is a
 *  valid target: a document-level shortcut listens there. */
export async function press(
  el: EventTarget | null | undefined,
  init: KeyboardEventInit,
): Promise<void> {
  await act(async () => {
    el?.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init }));
  });
}

/** Let pending promises settle inside `act`, for a component that fetches. */
export async function settle(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

export { act };
