/** A re-entrancy guard for actions that must not run twice at once.
 *
 * `disabled={busy}` alone is not enough: `busy` is React state, so a burst of
 * clicks delivered before the next render all see the old value and each
 * starts its own request. This holds the flag synchronously, outside React,
 * and mirrors it into state only so the buttons can grey out.
 *
 * `cooldownMs` keeps the guard held for a moment after a *successful* run. A
 * workflow transition swaps the button under the pointer — Submit for review
 * becomes Approve in the same spot — so a double click would otherwise land
 * its second half on the next action.
 */
export function createInFlightGuard(
  onChange: (busy: boolean) => void = () => {},
  cooldownMs = 0,
): <T>(work: () => Promise<T>) => Promise<T | undefined> {
  let held = false;
  return async <T>(work: () => Promise<T>): Promise<T | undefined> => {
    if (held) return undefined;
    held = true;
    onChange(true);
    let ok = false;
    try {
      const result = await work();
      ok = true;
      return result;
    } finally {
      if (ok && cooldownMs > 0) await new Promise((r) => setTimeout(r, cooldownMs));
      held = false;
      onChange(false);
    }
  };
}
