// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it } from 'vitest';

import { stagedJob } from './fixture';
import { ImportProgress } from './ImportProgress';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe('ImportProgress', () => {
  let root: ReturnType<typeof createRoot>;
  afterEach(() => {
    act(() => root.unmount());
    document.body.innerHTML = '';
  });

  it('shows processed of total, a bar and the five counts', () => {
    const job = stagedJob({
      status: 'running',
      total: 12,
      processed: 6,
      created: 3,
      updated: 1,
      skipped: 1,
      suppressed: 0,
      failed: 1,
    });
    root = createRoot(document.body.appendChild(document.createElement('div')));
    act(() => root.render(createElement(ImportProgress, { job })));
    expect(document.body.textContent).toContain('6 of 12 rows processed');
    expect(document.querySelector('[role="progressbar"]')).not.toBeNull();
    for (const label of ['Created', 'Updated', 'Skipped', 'Suppressed', 'Failed']) {
      expect(document.body.textContent).toContain(label);
    }
    expect(document.body.textContent).toContain('Running');
  });
});
