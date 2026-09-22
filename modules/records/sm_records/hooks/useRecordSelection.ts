import { useCallback, useEffect, useRef, useState } from 'react';

import * as model from '../utils/selection';

/**
 * The record list's selection state — `utils/selection`'s pure model plus the
 * two things only a component has: the anchor a Shift+click measures from,
 * and the reset that happens when the page underneath changes.
 *
 * **The reset is deliberate and it is the whole of the cross-page policy.** A
 * selection that survived a page change would let "Delete permanently, 12
 * records" mean twelve rows the operator can no longer see — and the list is
 * driven entirely by the URL, so a reload after a bulk action looks exactly
 * like a page change. Everything the toolbar acts on is on screen.
 */
export function useRecordSelection(uuids: readonly string[]) {
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set<string>());
  const anchor = useRef<string | null>(null);
  // The identity of "this page", as the rows it is showing. A sort, a filter,
  // a page step or a reload after a mutation all change it.
  const key = uuids.join(',');
  const previous = useRef(key);

  useEffect(() => {
    if (previous.current === key) return;
    previous.current = key;
    anchor.current = null;
    setSelected(new Set<string>());
  }, [key]);

  const toggle = useCallback(
    (uuid: string, extend = false) => {
      setSelected((current) =>
        extend ? model.range(current, uuids, anchor.current, uuid) : model.toggle(current, uuid),
      );
      // The anchor moves to every plain click and stays put across a range,
      // so a second Shift+click re-measures from the same row rather than
      // walking the selection down the page one gesture at a time.
      if (!extend) anchor.current = uuid;
    },
    [uuids],
  );

  const toggleAll = useCallback(() => {
    setSelected((current) =>
      model.allSelected(current, uuids)
        ? model.deselectAll(current, uuids)
        : model.selectAll(current, uuids),
    );
    anchor.current = null;
  }, [uuids]);

  const clear = useCallback(() => {
    setSelected(new Set<string>());
    anchor.current = null;
  }, []);

  /** Drop what a refused batch named, keeping the rest ticked. */
  const deselect = useCallback((failing: readonly string[]) => {
    setSelected((current) => model.without(current, failing));
  }, []);

  return {
    selected,
    /** In page order, and only rows this page is showing — what every action sends. */
    uuids: model.visible(selected, uuids),
    count: model.visible(selected, uuids).length,
    isSelected: (uuid: string) => selected.has(uuid),
    allSelected: model.allSelected(selected, uuids),
    someSelected: model.someSelected(selected, uuids),
    toggle,
    toggleAll,
    clear,
    deselect,
  };
}

export type RecordSelection = ReturnType<typeof useRecordSelection>;
