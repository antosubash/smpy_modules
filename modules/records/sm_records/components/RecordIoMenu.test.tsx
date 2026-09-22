// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { mount } from '../test-dom';
import type { ImportReport } from '../utils/io';
import { DEFAULT_IMPORT_OPTIONS } from './RecordImportOptions';

let hookState: ReturnType<typeof baseHook>;

function baseHook() {
  return {
    file: new File(['a'], 'import.csv'),
    report: null as ImportReport | null,
    phase: 'idle' as const,
    options: DEFAULT_IMPORT_OPTIONS,
    busy: false,
    limitText: '50 MB',
    pick: vi.fn(async () => true),
    changeOptions: vi.fn(),
    apply: vi.fn(async () => undefined),
    close: vi.fn(),
  };
}

vi.mock('../hooks/useRecordImport', () => ({
  useRecordImport: () => hookState,
}));

const { RecordIoMenu } = await import('./RecordIoMenu');

function dirtyReport(): ImportReport {
  return {
    dry_run: true,
    mode: 'upsert',
    total: 3,
    created: 2,
    updated: 0,
    skipped: 0,
    failed: 1,
    errors: [{ row: 3, field: 'capacity', message: 'not an integer' }],
    errors_truncated: false,
    duration_ms: 5,
  };
}

function cleanReport(): ImportReport {
  return { ...dirtyReport(), created: 3, failed: 0, errors: [] };
}

/** Radix's Dialog renders its content into a portal on `document.body`, not
 *  under the mount host — see `RecordActions.test.tsx` for the same note. */
function inDoc(selector: string): HTMLElement | null {
  return document.querySelector(selector);
}

describe('RecordIoMenu — U3: a bad row explains itself instead of removing Apply', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    hookState = baseHook();
  });

  it('keeps the Apply button present but disabled, with a reason, when a row failed', async () => {
    hookState.report = dirtyReport();
    const view = await mount(<RecordIoMenu typeKey="book" search="" canEdit fields={[]} />);
    const applyBtn = inDoc('[data-testid="records-import-apply"]');
    expect(applyBtn).not.toBeNull();
    expect(applyBtn?.hasAttribute('disabled')).toBe(true);
    const reason = inDoc('[data-testid="records-import-blocked"]');
    expect(reason?.textContent).toContain("can't be imported");
    expect(reason?.textContent).toContain('Skip it and write the rest');
    expect(reason?.getAttribute('role')).toBe('alert');
    expect(applyBtn?.getAttribute('aria-describedby')).toBe('records-import-blocked');
    await view.unmount();
  });

  it('enables Apply, with no blocked message, once on_error is switched to skip', async () => {
    hookState.report = dirtyReport();
    hookState.options = { ...DEFAULT_IMPORT_OPTIONS, onError: 'skip' };
    const view = await mount(<RecordIoMenu typeKey="book" search="" canEdit fields={[]} />);
    const applyBtn = inDoc('[data-testid="records-import-apply"]');
    expect(applyBtn?.hasAttribute('disabled')).toBe(false);
    expect(inDoc('[data-testid="records-import-blocked"]')).toBeNull();
    await view.unmount();
  });

  it('enables Apply with no blocked message on a clean report', async () => {
    hookState.report = cleanReport();
    const view = await mount(<RecordIoMenu typeKey="book" search="" canEdit fields={[]} />);
    const applyBtn = inDoc('[data-testid="records-import-apply"]');
    expect(applyBtn?.hasAttribute('disabled')).toBe(false);
    expect(inDoc('[data-testid="records-import-blocked"]')).toBeNull();
    await view.unmount();
  });
});
