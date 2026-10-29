// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it } from 'vitest';

import type { SlotValues, TestResult } from '../utils/api';
import { SlotCard } from './SlotCard';

// `@simple-module-py/ui` is compiled against a global `React`.
(globalThis as unknown as { React: unknown }).React = React;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const values: SlotValues = {
  provider: 'openai_compatible',
  model: 'qwen',
  base_url: 'http://vllm:8000/v1',
  api_key: '',
  clear_key: false,
};

// QA (ship round 1, TEST-001): a probe of a slow model showed nothing for
// 8 s - no pending state - so it looked as if the click did nothing.
describe('SlotCard — Test connection feedback', () => {
  let root: Root | undefined;
  let host: HTMLDivElement | undefined;

  afterEach(() => {
    act(() => root?.unmount());
    host?.remove();
  });

  async function mount(testing: boolean, testResult: TestResult | null) {
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
          dirty={false}
          busy={testing}
          testing={testing}
          testResult={testResult}
          onChange={() => {}}
          onTest={() => {}}
          onLoadModels={async () => ({ ok: true, models: [], error: '' })}
        />,
      );
    });
  }
  const q = (id: string) => host?.querySelector(`[data-testid="${id}"]`);

  it('says it is testing while the probe runs', async () => {
    await mount(true, null);
    expect(q('chat-test-button')?.textContent).toBe('Testing…');
    const pending = q('chat-test-pending');
    expect(pending?.textContent).toContain('Waiting for the model');
    expect(pending?.closest('[aria-live="polite"]')).not.toBeNull();
  });

  it('shows the model that answered once it succeeded', async () => {
    await mount(false, { ok: true, model: 'qwen', latency_ms: 812, error: null } as TestResult);
    expect(q('chat-test-button')?.textContent).toBe('Test connection');
    expect(q('chat-test-pending')).toBeNull();
    expect(q('chat-test-result')?.textContent).toBe('OK — qwen (812 ms)');
  });

  it('shows the error when it failed', async () => {
    await mount(false, { ok: false, model: 'qwen', latency_ms: null, error: 'Timed out after 30s.' } as TestResult);
    expect(q('chat-test-result')?.textContent).toBe('Timed out after 30s.');
  });
});
