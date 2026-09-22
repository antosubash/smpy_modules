// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { act, mount } from '../test-dom';
import type { ImportReport } from '../utils/io';

const calls: { dryRun: boolean; mode: string }[] = [];
let pending: ((report: ImportReport) => void)[] = [];

vi.mock('@inertiajs/react', () => ({ router: { reload: vi.fn() } }));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock('../utils/io', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../utils/io')>();
  return {
    ...actual,
    importRecords: (_key: string, _file: File, options: { dryRun?: boolean; mode?: string }) => {
      calls.push({ dryRun: options.dryRun ?? true, mode: options.mode ?? 'upsert' });
      return new Promise<ImportReport>((resolve) => {
        pending.push(resolve);
      });
    },
  };
});

const { useRecordImport } = await import('./useRecordImport');
const { DEFAULT_MAX_IMPORT_BYTES } = await import('../utils/io');

function report(mode: string): ImportReport {
  return {
    dry_run: true,
    mode,
    total: 1,
    created: 1,
    updated: 0,
    skipped: 0,
    failed: 0,
    errors: [],
    errors_truncated: false,
    duration_ms: 1,
  };
}

type Hook = ReturnType<typeof useRecordImport>;

/** A probe that hands the hook's return value back to the test — there is
 *  no `renderHook` in this repo. */
function Probe({ onRender }: { onRender: (hook: Hook) => void }) {
  onRender(useRecordImport('book', DEFAULT_MAX_IMPORT_BYTES));
  return null;
}

async function mountHook() {
  let latest: Hook | null = null;
  const view = await mount(
    <Probe
      onRender={(hook) => {
        latest = hook;
      }}
    />,
  );
  return { view, hook: () => latest as unknown as Hook };
}

const FILE = new File(['[]'], 'rows.json', { type: 'application/json' });

describe('useRecordImport — R10: overlapping dry runs are sequenced', () => {
  beforeEach(() => {
    calls.length = 0;
    pending = [];
  });

  it('starts the run outside the setState updater — one POST per change', async () => {
    const { view, hook } = await mountHook();
    await act(async () => {
      void hook().pick(FILE);
    });
    expect(calls).toHaveLength(1);

    await act(async () => {
      hook().changeOptions({ mode: 'create' });
    });
    // Exactly one new request: the run used to live inside the `setOptions`
    // updater, which React is free to re-invoke — and did, it would POST the
    // file twice.
    expect(calls).toHaveLength(2);
    expect(calls[1].mode).toBe('create');
    view.unmount();
  });

  it('ignores a stale response and keeps the spinner up for the live one', async () => {
    const { view, hook } = await mountHook();
    await act(async () => {
      void hook().pick(FILE);
    });
    await act(async () => {
      hook().changeOptions({ mode: 'create' });
    });
    expect(pending).toHaveLength(2);

    // The *first* request answers last — the race the review describes.
    await act(async () => {
      pending[0](report('upsert'));
    });
    expect(hook().report).toBeNull();
    // …and its `finally` must not clear the phase while the second is still
    // in flight.
    expect(hook().phase).toBe('checking');
    expect(hook().busy).toBe(true);

    await act(async () => {
      pending[1](report('create'));
    });
    expect(hook().report?.mode).toBe('create');
    expect(hook().phase).toBe('idle');
    view.unmount();
  });
});
