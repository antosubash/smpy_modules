import { Button } from '@simple-module-py/ui/components/ui/button';
import { type ReactNode, useRef } from 'react';

/**
 * One footer paging button (First, Previous, Next, Last, First page, Next
 * page) that never throws keyboard focus away.
 *
 * A focused button that becomes `disabled` loses focus to `<body>` (the
 * HTML focus fixup rule), and the pagers used to disable every button while
 * a page change was in flight — so each Enter on "Next" sent the next Tab
 * back to the top of the document, sidebar included (review 4, ux F2). So:
 *
 * - **In flight** (`busy`) the button stays enabled, is `aria-disabled` and
 *   ignores presses — the double-click race U12 closed stays closed.
 * - **Unavailable** (`unavailable`: the first or last page) it is natively
 *   `disabled`, out of the tab order — unless it holds focus right now,
 *   which is exactly "Next" landing on the last page: it is then
 *   `aria-disabled` instead, and becomes `disabled` on the first render
 *   after focus has moved on.
 */
export function PagerButton({
  unavailable = false,
  busy = false,
  onPress,
  children,
}: {
  unavailable?: boolean;
  busy?: boolean;
  onPress: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLButtonElement>(null);
  // Read at render, before this commit can disable it: the one moment the
  // browser still says where focus is.
  const holdsFocus =
    ref.current !== null && ref.current.ownerDocument.activeElement === ref.current;
  const inert = unavailable || busy;
  return (
    <Button
      ref={ref}
      type="button"
      variant="outline"
      size="sm"
      disabled={unavailable && !holdsFocus}
      aria-disabled={inert || undefined}
      className="aria-disabled:cursor-not-allowed aria-disabled:opacity-50"
      onClick={() => {
        if (!inert) onPress();
      }}
    >
      {children}
    </Button>
  );
}
