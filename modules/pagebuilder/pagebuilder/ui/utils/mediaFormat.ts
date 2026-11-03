/** Formatting and parsing helpers for the media library UI. */

export function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

export function parseKB(raw: string): number | undefined {
  const trimmed = raw.trim();
  if (!trimmed) return undefined;
  const n = Number(trimmed);
  if (!Number.isFinite(n) || n < 0) return undefined;
  return Math.round(n * 1024);
}

export function uploadKey(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}:${Math.random().toString(36).slice(2, 8)}`;
}
