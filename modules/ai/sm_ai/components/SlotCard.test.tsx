// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ModelsResult, SlotValues } from '../utils/api';
import { SlotCard } from './SlotCard';

// `@simple-module-py/ui` is compiled against a global `React`.
(globalThis as unknown as { React: unknown }).React = React;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const values: SlotValues = {
  provider: 'openai_compatible',
  model: '',
  base_url: 'http://vllm:8000/v1',
  api_key: '',
  clear_key: false,
};

describe('SlotCard — Load models', () => {
  let root: Root | undefined;
  let host: HTMLDivElement | undefined;

  afterEach(() => {
    act(() => root?.unmount());
    host?.remove();
  });

  async function mount(onLoadModels: () => Promise<ModelsResult>, dirty = false) {
    host = document.createElement('div');
    document.body.append(host);
    root = createRoot(host);
    await act(async () => {
      root?.render(
        <SlotCard
          title="Chat"
          description=""
          idPrefix="chat"
          providers={['openai_compatible']}
          optionalSlot={false}
          values={values}
          hasStoredKey={false}
          dirty={dirty}
          busy={false}
          testResult={null}
          onChange={() => {}}
          onTest={() => {}}
          onLoadModels={onLoadModels}
        />,
      );
    });
    const button = () =>
      Array.from(host?.querySelectorAll('button') ?? []).find(
        (b) => b.textContent === 'Load models',
      );
    return { button };
  }

  it('offers the listed models as suggestions for the model field', async () => {
    const { button } = await mount(async () => ({ ok: true, models: ['a', 'b'], error: '' }));
    await act(async () => button()?.click());

    const input = host?.querySelector<HTMLInputElement>('#chat-model');
    const list = host?.querySelector(`datalist#${CSS.escape(input?.getAttribute('list') ?? '')}`);
    expect(Array.from(list?.querySelectorAll('option') ?? []).map((o) => o.value)).toEqual([
      'a',
      'b',
    ]);
    expect(host?.querySelector('[data-testid="chat-models-result"]')?.textContent).toContain(
      'Models found: 2',
    );
  });

  it('shows a failure inline and adds no suggestions', async () => {
    const { button } = await mount(async () => ({
      ok: false,
      models: [],
      error: 'Connection refused',
    }));
    await act(async () => button()?.click());

    expect(host?.querySelector('#chat-model')?.hasAttribute('list')).toBe(false);
    expect(host?.querySelector('[data-testid="chat-models-result"]')?.textContent).toBe(
      'Connection refused',
    );
  });

  it('is disabled while the form has unsaved edits', async () => {
    const load = vi.fn(async () => ({ ok: true, models: [], error: '' }));
    const { button } = await mount(load, true);

    expect(button()?.disabled).toBe(true);
  });
});
