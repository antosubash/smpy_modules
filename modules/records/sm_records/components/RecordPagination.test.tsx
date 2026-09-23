// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';

import { click, mount } from '../test-dom';
import { RecordPagination } from './RecordPagination';

function pagination(loading: boolean) {
  return (
    <RecordPagination
      page={2}
      pageSize={25}
      total={100}
      capped={false}
      itemCount={25}
      loading={loading}
      onGo={vi.fn()}
      onPageSize={vi.fn()}
    />
  );
}

describe('RecordPagination — U12: the pager disables itself while a page change is in flight', () => {
  it('leaves First/Previous/Next/Last and the page-size select enabled when idle', async () => {
    const view = await mount(pagination(false));
    for (const label of ['First', 'Previous', 'Next', 'Last']) {
      expect((view.button(label) as HTMLButtonElement).disabled).toBe(false);
    }
    expect(view.find<HTMLSelectElement>('#records-page-size')?.disabled).toBe(false);
    await view.unmount();
  });

  it('disables every control while loading, on top of whatever First/Last already disable', async () => {
    const view = await mount(pagination(true));
    for (const label of ['First', 'Previous', 'Next', 'Last']) {
      expect((view.button(label) as HTMLButtonElement).disabled).toBe(true);
    }
    expect(view.find<HTMLSelectElement>('#records-page-size')?.disabled).toBe(true);
    await view.unmount();
  });
});

type Overrides = Partial<Parameters<typeof RecordPagination>[0]>;

function pager(overrides: Overrides = {}) {
  const props = {
    page: 2 as number | null,
    pageSize: 25,
    total: 32,
    capped: true,
    itemCount: 25,
    nextCursor: 'NEXT' as string | null,
    onGo: vi.fn(),
    onContinue: vi.fn(),
    onPageSize: vi.fn(),
    ...overrides,
  };
  return { props, element: <RecordPagination {...props} /> };
}

const disabled = (el: HTMLElement | undefined) => (el as HTMLButtonElement).disabled;

describe('RecordPagination — past the cap, Next continues by cursor', () => {
  it('on the capped last page, Next follows next_cursor instead of a page number', async () => {
    const { props, element } = pager();
    const view = await mount(element);
    expect(disabled(view.button('Next'))).toBe(false);
    await click(view.button('Next'));
    expect(props.onContinue).toHaveBeenCalledWith('NEXT');
    expect(props.onGo).not.toHaveBeenCalled();
    // Last is still the cap's last page — which is this one.
    expect(disabled(view.button('Last'))).toBe(true);
    await view.unmount();
  });

  it('before the capped last page, Next is still a numbered page', async () => {
    const { props, element } = pager({ page: 1 });
    const view = await mount(element);
    await click(view.button('Next'));
    expect(props.onGo).toHaveBeenCalledWith(2);
    expect(props.onContinue).not.toHaveBeenCalled();
    await view.unmount();
  });

  it('a capped last page with no cursor is the end: Next is disabled', async () => {
    const view = await mount(pager({ nextCursor: null, itemCount: 8 }).element);
    expect(disabled(view.button('Next'))).toBe(true);
    await view.unmount();
  });

  it('an exact total ends at its last page even when that page was full', async () => {
    const view = await mount(pager({ capped: false, total: 50 }).element);
    expect(disabled(view.button('Next'))).toBe(true);
    await view.unmount();
  });
});

describe('RecordPagination — cursor mode (a page reached by ?after=)', () => {
  it('shows First page / Next page and the sentence, and no numbers, Previous or Last', async () => {
    const view = await mount(pager({ page: null }).element);
    expect(view.find('[data-testid="records-cursor-pager"]')).not.toBeNull();
    expect(view.find('[data-testid="records-page-cursor"]')?.textContent).toBe(
      'The list continues in the same order from here, without page numbers.',
    );
    expect(view.find('[data-testid="records-page-position"]')).toBeNull();
    expect(view.host.textContent).not.toMatch(/Showing/);
    const labels = view.all('button').map((b) => b.textContent);
    expect(labels).toEqual(['First page', 'Next page']);
    expect(view.find('#records-page-size')).not.toBeNull();
    await view.unmount();
  });

  it('First page goes to page 1 and Next page follows next_cursor', async () => {
    const { props, element } = pager({ page: null, nextCursor: 'AFTER-2' });
    const view = await mount(element);
    await click(view.button('First page'));
    expect(props.onGo).toHaveBeenCalledWith(1);
    await click(view.button('Next page'));
    expect(props.onContinue).toHaveBeenCalledWith('AFTER-2');
    await view.unmount();
  });

  it('disables Next page at the end of the list, and renders even on an empty page', async () => {
    const view = await mount(
      pager({ page: null, nextCursor: null, itemCount: 0, total: 0, capped: false }).element,
    );
    expect(disabled(view.button('Next page'))).toBe(true);
    expect(disabled(view.button('First page'))).toBe(false);
    await view.unmount();
  });

  it('disables both while a request is in flight', async () => {
    const view = await mount(pager({ page: null, loading: true }).element);
    expect(disabled(view.button('First page'))).toBe(true);
    expect(disabled(view.button('Next page'))).toBe(true);
    await view.unmount();
  });
});
