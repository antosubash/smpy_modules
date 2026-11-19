/** Which of two text colours reads better on a calendar's colour (WCAG 2 contrast). */
export const LIGHT_TEXT = '#ffffff';
export const DARK_TEXT = '#111827';

function channels(hex: string): [number, number, number] | null {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex.trim());
  if (!m) return null;
  return [
    Number.parseInt(m[1] ?? '0', 16),
    Number.parseInt(m[2] ?? '0', 16),
    Number.parseInt(m[3] ?? '0', 16),
  ];
}

/** Relative luminance, 0 (black) to 1 (white). */
export function luminance(hex: string): number {
  const rgb = channels(hex) ?? [0, 0, 0];
  const [r, g, b] = rgb.map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** Contrast ratio of two colours, 1 to 21. */
export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

/** The text colour with the higher contrast on `background`; `undefined` for a colour that
 *  is not `#rrggbb`, which keeps the theme's own text colour. */
export function readableOn(background: string | null | undefined): string | undefined {
  if (!background || !channels(background)) return undefined;
  return contrast(background, DARK_TEXT) >= contrast(background, LIGHT_TEXT)
    ? DARK_TEXT
    : LIGHT_TEXT;
}
