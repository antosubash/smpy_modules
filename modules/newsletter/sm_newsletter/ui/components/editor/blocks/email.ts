/**
 * Inline styles the canvas approximates the email with.
 *
 * Only an approximation: the email itself is built server-side
 * (`content/render/`), with the branding's accent colour, and the preview pane
 * shows that. These keep the canvas close enough to write in — a 600 px
 * column, one font, one accent — using inline styles because that is what the
 * email is made of.
 */

import type { CSSProperties } from 'react';

/** Mirrors `content/render/styles.py` (and the email's default accent); keep them in step. */
export const ACCENT = '#2563eb';
const TEXT = '#222222';
export const MUTED = '#71717a';
export const RULE = '#e4e4e7';
export const PAGE_BG = '#f4f4f5';
export const FONT = '-apple-system, Segoe UI, Helvetica, Arial, sans-serif';

/** The cell every block sits in, as in the email (`styles.CELL`). */
export const block: CSSProperties = { padding: '0 32px 16px', fontFamily: FONT, color: TEXT };

export type Align = 'left' | 'center' | 'right';
