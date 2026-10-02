/**
 * Parsing for the block fields that take one item per line.
 *
 * Several blocks here are edited as a textarea rather than through Puck's array
 * field, because a writer pasting a list, a set of sources or a table out of a
 * document gets it in one action instead of clicking "add item" nine times.
 * That choice only pays off if every block agrees on what a line means, so the
 * rule lives here rather than being re-typed in each render.
 */

/** Trimmed, non-empty lines. A blank line is spacing, not an empty item. */
export function lines(value: string | undefined): string[] {
  return (value ?? '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
}

/**
 * One line split on `|` into exactly `count` trimmed cells.
 *
 * Short rows are padded with `''` so a caller can destructure without guarding
 * — a source with no URL is a citation, not a broken row. Anything beyond
 * `count` is folded back into the last cell, because the overflow is almost
 * always a caption or title that happened to contain a pipe, and dropping the
 * remainder would silently truncate a writer's sentence.
 *
 * Table rows do not use this: their width is whatever the writer typed, so
 * they split with `row` instead.
 */
export function cells(line: string, count: number): string[] {
  const parts = line.split('|').map((part) => part.trim());
  if (parts.length <= count) {
    return [...parts, ...Array(count - parts.length).fill('')];
  }
  return [...parts.slice(0, count - 1), parts.slice(count - 1).join(' | ')];
}

/** One table row, split on `|` into as many cells as it holds.
 *
 * A leading or trailing pipe is tolerated and dropped, so a row pasted in
 * Markdown style (`| a | b |`) does not gain empty cells at both ends.
 */
export function row(line: string): string[] {
  return line
    .replace(/^\s*\|/, '')
    .replace(/\|\s*$/, '')
    .split('|')
    .map((cell) => cell.trim());
}

/**
 * A React key for an item whose only identity is its text.
 *
 * Two identical bullets are a real thing to write, and keying on the text alone
 * makes React treat the second as a duplicate of the first.
 */
export function itemKey(text: string, index: number): string {
  return `${index}:${text}`;
}
