/** A byte count for a person: "5 MB", "1.5 MB", "64 KB". Other modules keep their own copies;
 *  a module imports another only through its index. */
export function formatBytes(bytes: number): string {
  const mb = bytes / (1024 * 1024);
  return mb >= 1
    ? `${Number.isInteger(mb) ? mb : mb.toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}
