// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Segment } from '../../utils/types';
import { SegmentTable } from './SegmentTable';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe('SegmentTable', () => {
  let root: ReturnType<typeof createRoot>;
  afterEach(() => {
    act(() => root.unmount());
    document.body.innerHTML = '';
  });

  it('breaks a long unbroken name so Edit and Delete stay in view', () => {
    const name = 'x'.repeat(200);
    const segment: Segment = { id: 1, name, list_type_key: 'news', rules: [], updated_at: null };
    root = createRoot(document.body.appendChild(document.createElement('div')));
    act(() =>
      root.render(
        createElement(SegmentTable, {
          items: [segment],
          fields: [],
          canEdit: true,
          onEdit: vi.fn(),
          onDeleted: vi.fn(),
        }),
      ),
    );
    const cell = [...document.querySelectorAll('td')].find((c) => c.textContent === name);
    expect(cell?.className).toContain('break-all');
    expect(cell?.getAttribute('title')).toBe(name);
  });
});
