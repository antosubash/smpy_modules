import { useEffect, useState } from 'react';

/**
 * `value`, trimmed, once it has stopped changing for `delayMs`: what a search
 * box sends to the server instead of every keystroke.
 */
export function useDebounced(value: string, delayMs = 250): string {
  const [debounced, setDebounced] = useState(value.trim());
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value.trim()), delayMs);
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}
