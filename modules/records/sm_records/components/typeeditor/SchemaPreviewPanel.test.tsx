// @vitest-environment happy-dom
import { act } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { click, mount } from '../../test-dom';
import type { SchemaPreview, TypeRead } from '../../utils/types';

const previewSchema = vi.fn();

vi.mock('@inertiajs/react', () => ({
  Link: ({ children, ...rest }: { children?: unknown; [key: string]: unknown }) => (
    // biome-ignore lint/suspicious/noExplicitAny: a thin passthrough stand-in for Inertia's Link
    <a {...(rest as any)}>{children as React.ReactNode}</a>
  ),
}));
vi.mock('../../utils/api', () => ({
  ApiError: class ApiError extends Error {
    status = 0;
  },
  getPreviewJob: vi.fn(),
  previewSchema: (...args: unknown[]) => previewSchema(...args),
}));

const { SchemaPreviewPanel } = await import('./SchemaPreviewPanel');

const SAVED = {
  key: 'product',
  fields: [],
  display_field: 'name',
  slug_field: null,
} as unknown as TypeRead;

function report(failing: number): SchemaPreview {
  return {
    kind: 'additive',
    changes: [],
    report: {
      checked: 5,
      failing,
      sample: [],
      orphaned_conflicts: {},
      clean: failing === 0,
    },
  };
}

const LINK = '[data-testid="records-check-records-link"]';

async function press(testid: string, result: SchemaPreview) {
  previewSchema.mockReset();
  previewSchema.mockResolvedValue(result);
  const view = await mount(
    <SchemaPreviewPanel
      typeKey="product"
      saved={SAVED}
      fields={[]}
      displayField="name"
      slugField=""
      dirty
    />,
  );
  await click(view.find(`[data-testid="${testid}"]`));
  // The handler awaits the request; the state it then sets lands a microtask
  // later than the click itself.
  await act(async () => {
    await Promise.resolve();
  });
  return view;
}

describe('R7c: "Check records" hands over the worklist it just wrote', () => {
  it('links to the list filtered by the flag the scan set', async () => {
    const view = await press('records-check-records', report(2));
    // The report names at most DRY_RUN_SAMPLE records; the scan marked every
    // one, so the link is where the rest of them are.
    expect(previewSchema.mock.calls[0]?.[1]).toMatchObject({ rescan: true });
    expect(view.find<HTMLAnchorElement>(LINK)?.getAttribute('href')).toBe(
      '/admin/records/product?filter=invalid:eq:true',
    );
    await view.unmount();
  });

  it('offers nothing to open when the scan found nothing', async () => {
    const view = await press('records-check-records', report(0));
    expect(view.find(LINK)).toBeNull();
    await view.unmount();
  });

  it('stays out of a draft preview, which marked nothing', async () => {
    const view = await press('records-preview-changes', report(2));
    // The same failing report, from the button that scans a *proposal*: it
    // wrote no marks, so a link to the marked records would list whatever an
    // earlier check left behind under a report about something else.
    expect(previewSchema.mock.calls[0]?.[1]).not.toMatchObject({ rescan: true });
    expect(view.find('[data-testid="records-schema-preview"]')).not.toBeNull();
    expect(view.find(LINK)).toBeNull();
    await view.unmount();
  });
});

describe('U3: the link never claims a count its own destination might not show', () => {
  it('carries no count in its own label — the live-only worklist could show fewer', async () => {
    const view = await press('records-check-records', report(12));
    // `report.failing` counts live *and* trashed records; the worklist this
    // links to (`?filter=invalid:eq:true`, no `trashed=`) lists live ones
    // only. The count moved to a sentence above the link instead of sitting
    // inside a promise the link's own destination could contradict.
    expect(view.find(LINK)?.textContent).toBe('Show the marked records');
    await view.unmount();
  });

  it('discloses the wider (live + trashed) scope next to the link', async () => {
    const view = await press('records-check-records', report(12));
    // (i18next is unconfigured under vitest, so `{count}` is not
    // interpolated here — see `RecordRowAction.test.tsx`'s U27 tests for
    // the same note. What matters is that the disclosure sentence itself
    // renders, mentioning the Trash.)
    const note = view.find('[data-testid="records-schema-preview"] p.text-muted-foreground');
    expect(note?.textContent).toContain('{count}');
    expect(note?.textContent).toContain('Trash');
    await view.unmount();
  });
});
