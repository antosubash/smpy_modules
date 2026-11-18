/** The grid without FullCalendar: records its props and lets a test fire what the real grid
 *  would. Never shipped (the wheel excludes `*-test-support.tsx`), and it imports vitest. */
import { type Ref, useImperativeHandle } from 'react';
import { type Mock, vi } from 'vitest';
import type { Range } from '../time/range';
import type { CreateSlot, GridHandle, GridProps, OccurrenceChange } from '../types';

type Handle = Record<keyof GridHandle, Mock>;
const makeHandle = (): Handle => ({
  today: vi.fn(),
  prev: vi.fn(),
  next: vi.fn(),
  setView: vi.fn(),
  gotoDate: vi.fn(),
  focusEvent: vi.fn(),
});

export const fakeGrid = {
  last: null as GridProps | null,
  handle: makeHandle(),
  reset() {
    fakeGrid.last = null;
    fakeGrid.handle = makeHandle();
  },
  /** The grid reports a visible range (what `datesSet` does). */
  emitRange(visible: Range, title: string, view?: GridProps['view'], date?: string) {
    const grid = fakeGrid.last;
    grid?.onRangeChange({ visible, title, view: view ?? grid.view, date: date ?? grid.date });
  },
  open(key: string, element: HTMLElement = document.body) {
    const occurrence = fakeGrid.last?.items.find((o) => o.key === key);
    if (occurrence) fakeGrid.last?.onEventOpen(occurrence, element);
  },
  select(slot: CreateSlot) {
    fakeGrid.last?.editing?.onCreate(slot);
  },
  change(change: OccurrenceChange): Promise<boolean> | undefined {
    return fakeGrid.last?.editing?.onChange(change);
  },
};

export default function FakeGrid({ ref, ...grid }: GridProps & { ref?: Ref<GridHandle> }) {
  fakeGrid.last = grid;
  useImperativeHandle(ref, () => fakeGrid.handle as unknown as GridHandle);
  return (
    <div data-testid="fake-grid">
      {grid.items.map((o) => (
        <div key={o.key} data-key={o.key}>
          {grid.renderChip(o, '09:00')}
        </div>
      ))}
    </div>
  );
}
