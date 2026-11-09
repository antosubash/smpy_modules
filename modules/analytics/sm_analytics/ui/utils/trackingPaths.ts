/** Match explicit routes before collecting any pathname. */
const EXCLUDED = new Set(['auth', 'login', 'logout', 'register', 'settings', 'analytics']);

export function matchPath(
  path: string,
  patterns: string[],
  kind: 'public' | 'application',
): string | null {
  const clean = path.split(/[?#]/, 1)[0];
  if (!clean.startsWith('/') || clean.startsWith('//')) return null;
  let decoded: string;
  try {
    decoded = decodeURIComponent(clean);
  } catch {
    return null;
  }
  if (
    decoded
      .split('/')
      .some((part) => EXCLUDED.has(part.toLowerCase()) || part === '.' || part === '..')
  )
    return null;
  const segments = clean.split('/');
  for (const pattern of patterns) {
    const expected = pattern.split('/');
    if (expected.length !== segments.length) continue;
    if (
      expected.every((part, i) =>
        part.startsWith(':') ? Boolean(segments[i]) : part === segments[i],
      )
    ) {
      return kind === 'application' ? pattern : clean;
    }
  }
  return null;
}
