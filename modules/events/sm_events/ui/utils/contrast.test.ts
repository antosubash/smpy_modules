import { describe, expect, it } from 'vitest';
import { contrast, DARK_TEXT, LIGHT_TEXT, readableOn } from './contrast';

describe('readableOn', () => {
  it('picks dark text on light colours and light text on dark ones', () => {
    expect(readableOn('#84cc16')).toBe(DARK_TEXT); // lime
    expect(readableOn('#facc15')).toBe(DARK_TEXT);
    expect(readableOn('#ffffff')).toBe(DARK_TEXT);
    expect(readableOn('#2563eb')).toBe(LIGHT_TEXT);
    expect(readableOn('#000000')).toBe(LIGHT_TEXT);
  });
  it('reaches 4.5:1 on every palette-like colour', () => {
    const palette = ['#dc2626', '#16a34a', '#2563eb', '#84cc16', '#facc15', '#f97316', '#0ea5e9'];
    for (const color of palette) {
      const text = readableOn(color) ?? '';
      expect(contrast(color, text), color).toBeGreaterThanOrEqual(4.5);
    }
  });
  it('leaves a colour it cannot read to the theme', () => {
    expect(readableOn('red')).toBeUndefined();
    expect(readableOn(null)).toBeUndefined();
  });
});
