// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';

import { mount } from '../test-dom';

vi.mock('@inertiajs/react', () => ({
  Link: ({ children, href }: { children?: unknown; href: string }) => (
    <a href={href}>{children as React.ReactNode}</a>
  ),
  router: { visit: vi.fn() },
}));
let ioProps: Record<string, unknown> = {};
vi.mock('./RecordIoMenu', () => ({
  RecordIoMenu: (props: Record<string, unknown>) => {
    ioProps = props;
    return <button type="button">Export</button>;
  },
}));

const { RecordListActions, TOOLBAR_CLASS } = await import('./RecordListActions');

/**
 * Review 4, ux F1: at 720×450 (200% zoom of 1440×900) the six toolbar
 * buttons pushed the document to 745px, because the framework's `PageShell`
 * wraps `actions` in a `flex-shrink-0` box that sizes to its content — the
 * group's `flex-wrap` never had a narrower width to wrap into. happy-dom
 * lays nothing out, so the classes are what this pins; they were measured
 * with the real Tailwind build in Chromium against a copy of PageShell's
 * markup (720×450: 720 wide, two rows; 390×844: 390 wide; 1280 and up: one
 * row), and `records-columns.spec.ts` checks the document width on the
 * live list at 720 and 390.
 */
describe('RecordListActions — the toolbar wraps inside PageShell', () => {
  it('caps its own width against the viewport, so the buttons wrap from sm up', async () => {
    const view = await mount(
      <RecordListActions
        typeKey="book"
        fields={[]}
        canEdit
        trashed={false}
        exportSearch=""
        filtered={false}
        recordCount={3}
        columnsMenu={<button type="button">Columns</button>}
        onToggleTrashed={() => {}}
      />,
    );
    const group = view.find('[data-testid="records-list-actions"]');
    const classes = group?.className.split(/\s+/) ?? [];
    expect(classes).toEqual(expect.arrayContaining(['flex', 'flex-wrap', 'min-w-0']));
    // Room for the page padding and the title (and the sidebar from lg).
    expect(classes).toContain('sm:max-w-[calc(100vw-15rem)]');
    expect(classes).toContain('lg:max-w-[calc(100vw-32rem)]');
    expect(classes).not.toContain('shrink-0');
    expect(group?.className).toBe(TOOLBAR_CLASS);
    // Every control is inside the one wrapping group.
    expect(Array.from(group?.children ?? [], (el) => el.textContent)).toEqual([
      'Record Types',
      'Columns',
      'Export',
      'Trash',
      'New record',
    ]);
    await view.unmount();
  });
});

describe('RecordListActions — the export menu learns the count is capped', () => {
  it('passes total_capped through, so the menu can say "32+" (review 4, ux F4)', async () => {
    const view = await mount(
      <RecordListActions
        typeKey="book"
        fields={[]}
        canEdit={false}
        trashed={false}
        exportSearch="filter=a%3Aeq%3Ab"
        filtered
        recordCount={32}
        recordCountCapped
        onToggleTrashed={() => {}}
      />,
    );
    expect(ioProps).toMatchObject({ recordCount: 32, recordCountCapped: true, filtered: true });
    await view.unmount();
  });
});

describe('RecordListActions — the tenant badge (tenancy design §J)', () => {
  it('shows nothing when tenancyMode is absent or single', async () => {
    const view = await mount(
      <RecordListActions
        typeKey="book"
        fields={[]}
        canEdit={false}
        trashed={false}
        exportSearch=""
        filtered={false}
        recordCount={0}
        tenant="acme"
        onToggleTrashed={() => {}}
      />,
    );
    expect(view.find('[data-testid="records-tenant-badge"]')).toBeNull();
    await view.unmount();
  });

  it('shows the bound tenant once tenancyMode is multi', async () => {
    const view = await mount(
      <RecordListActions
        typeKey="book"
        fields={[]}
        canEdit={false}
        trashed={false}
        exportSearch=""
        filtered={false}
        recordCount={0}
        tenant="acme"
        tenancyMode="multi"
        onToggleTrashed={() => {}}
      />,
    );
    // The badge rendering at all, gated on `tenancyMode`, is what this test
    // pins — and, with the catalogue loaded, that it names the tenant.
    const badge = view.find('[data-testid="records-tenant-badge"]');
    expect(badge?.textContent).toBe('Tenant: acme');
    await view.unmount();
  });
});
