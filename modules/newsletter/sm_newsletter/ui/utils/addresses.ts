/** Addresses separated by line breaks, commas or semicolons, trimmed, lower-cased, deduplicated. */
export function parseAddresses(text: string): string[] {
  const found = text
    .split(/[\n,;]+/)
    .map((a) => a.trim().toLowerCase())
    .filter(Boolean);
  return [...new Set(found)];
}
