// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';

import { click, mount } from '../test-dom';
import { RecordPagination } from './RecordPagination';

/**
 * Review 4, ux F2: Enter on a pager button disabled it for the request, and
 * a focused button that becomes `disabled` hands focus to <body> — each step
 * sent the next Tab back to the top of the document. Both pagers now keep
 * the pressed button focused: through the request (`aria-disabled`, not
 * `disabled`) and when the step lands on the last page (a button that holds
 * focus is not natively disabled).
 */
type Props = Parameters<typeof RecordPagination>[0];

function props(overrides: Partial<Props>): Props {
  return {
    page: 1,
    pageSize: 25,
    total: 50,
    capped: false,
    itemCount: 25,
    nextCursor: null,
    loading: false,
    onGo: vi.fn(),
    onContinue: vi.fn(),
    onPageSize: vi.fn(),
    ...overrides,
  };
}

const button = (label: string) =>
  Array.from(document.querySelectorAll('button')).find((b) => b.textContent === label) as
    | HTMLButtonElement
    | undefined;

describe('PagerButton — keyboard focus survives a page step', () => {
  it('numbered pager: Next keeps focus through the request and onto the last page', async () => {
    const onGo = vi.fn();
    const view = await mount(<RecordPagination {...props({ onGo })} />);
    const next = button('Next');
    next?.focus();
    await click(next);
    expect(onGo).toHaveBeenCalledWith(2);

    // In flight: the same button, still focused, marked but not disabled.
    await view.render(<RecordPagination {...props({ onGo, loading: true })} />);
    expect(document.activeElement).toBe(next);
    expect(next?.disabled).toBe(false);
    expect(next?.getAttribute('aria-disabled')).toBe('true');

    // Landed on page 2 of 2: Next is unavailable, but it holds focus, so it
    // says so with aria-disabled rather than dropping focus.
    await view.render(<RecordPagination {...props({ onGo, page: 2 })} />);
    expect(button('Next')).toBe(next);
    expect(document.activeElement).toBe(next);
    expect(next?.disabled).toBe(false);
    expect(next?.getAttribute('aria-disabled')).toBe('true');
    await click(next);
    expect(onGo).toHaveBeenCalledTimes(1);

    // Once focus moves on, it is an ordinary disabled button again.
    button('Previous')?.focus();
    await view.render(<RecordPagination {...props({ onGo, page: 2 })} />);
    expect(next?.disabled).toBe(true);
    await view.unmount();
  });

  it("Next on the cap's last page is the cursor page's Next page: same button, still focused", async () => {
    const onContinue = vi.fn();
    const capped = { total: 32, capped: true, onContinue };
    const view = await mount(
      <RecordPagination {...props({ ...capped, page: 2, nextCursor: 'C1' })} />,
    );
    const next = button('Next');
    next?.focus();
    await click(next);
    expect(onContinue).toHaveBeenCalledWith('C1');
    await view.render(<RecordPagination {...props({ ...capped, page: null, nextCursor: 'C2' })} />);
    expect(button('Next page')).toBe(next);
    expect(document.activeElement).toBe(next);
    await view.unmount();
  });

  it('cursor pager: Next page keeps focus through the request and at the end', async () => {
    const onContinue = vi.fn();
    const cursor = { page: null, total: 32, capped: true, onContinue };
    const view = await mount(<RecordPagination {...props({ ...cursor, nextCursor: 'C2' })} />);
    const next = button('Next page');
    next?.focus();
    await click(next);
    expect(onContinue).toHaveBeenCalledWith('C2');

    await view.render(
      <RecordPagination {...props({ ...cursor, nextCursor: 'C2', loading: true })} />,
    );
    expect(document.activeElement).toBe(next);
    expect(next?.disabled).toBe(false);

    // The next page is the list's last: no cursor, focus stays.
    await view.render(<RecordPagination {...props({ ...cursor, itemCount: 7 })} />);
    expect(document.activeElement).toBe(next);
    expect(next?.getAttribute('aria-disabled')).toBe('true');
    await click(next);
    expect(onContinue).toHaveBeenCalledTimes(1);
    await view.unmount();
  });
});
