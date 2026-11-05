// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from '../utils/api';
import type { Block } from '../utils/types';
import { PREVIEW_DELAY_MS, usePreview } from './usePreview';

vi.mock('../utils/api', () => ({ api: { preview: vi.fn(), previewUnsaved: vi.fn() } }));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const body: Block[] = [{ type: 'Heading', props: { id: 'h1', text: 'Hello', level: 'h1' } }];
const shown = { subject: 'Spring', html: '<p>x</p>', text: 'x', warnings: [] };

let input: Parameters<typeof usePreview>[0];
let result: ReturnType<typeof usePreview>;

function Harness() {
  result = usePreview(input);
  return null;
}

describe('usePreview', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(api.preview).mockReset().mockResolvedValue(shown);
    vi.mocked(api.previewUnsaved).mockReset().mockResolvedValue(shown);
  });
  afterEach(() => vi.useRealTimers());

  async function mount() {
    const root = createRoot(document.createElement('div'));
    await act(async () => root.render(createElement(Harness)));
    return root;
  }

  it('uses the unsaved body', async () => {
    input = { id: 3, editable: true, enabled: true, subject: 'Spring', preheader: 'p', body };
    await mount();
    expect(api.previewUnsaved).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(PREVIEW_DELAY_MS);
    });
    expect(api.previewUnsaved).toHaveBeenCalledWith({ subject: 'Spring', preheader: 'p', body });
    expect(api.preview).not.toHaveBeenCalled();
    expect(result.preview).toEqual(shown);
  });

  it('viewers use the saved preview', async () => {
    input = { id: 3, editable: false, enabled: true, subject: 'Spring', preheader: 'p', body };
    await mount();
    expect(api.preview).toHaveBeenCalledWith(3);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(PREVIEW_DELAY_MS * 2);
    });
    expect(api.previewUnsaved).not.toHaveBeenCalled();
    expect(result.preview).toEqual(shown);
  });
});
