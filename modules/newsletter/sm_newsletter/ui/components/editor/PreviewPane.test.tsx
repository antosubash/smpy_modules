// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from '../../utils/api';
import { PreviewPane } from './PreviewPane';

vi.mock('../../utils/api', () => ({
  api: { preview: vi.fn(), previewUnsaved: vi.fn() },
  errorMessage: () => 'failed',
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe('PreviewPane', () => {
  beforeEach(() => {
    vi.mocked(api.preview)
      .mockReset()
      .mockResolvedValue({
        subject: 'Spring',
        html: '<script>alert(1)</script>',
        text: 'plain',
        warnings: ['empty_body'],
      });
  });

  it('iframe is sandboxed with no tokens', async () => {
    const root = createRoot(document.body.appendChild(document.createElement('div')));
    await act(async () =>
      root.render(
        createElement(PreviewPane, {
          id: 1,
          editable: false,
          subject: 's',
          preheader: '',
          body: [],
        }),
      ),
    );
    await act(async () => {});
    const frame = document.querySelector('iframe') as HTMLIFrameElement;
    expect(frame.getAttribute('sandbox')).toBe('');
    expect(frame.getAttribute('srcdoc')).toContain('alert(1)');
    expect(document.querySelectorAll('li')).toHaveLength(1);
    act(() => root.unmount());
  });
});
