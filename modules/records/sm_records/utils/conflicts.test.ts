import { describe, expect, it } from 'vitest';

import { conflictField, humanizeCollisionDetail } from './conflicts';

/**
 * The strings under test are the literal `f"..."` payloads of
 * `services/_claims.py` — copied verbatim, so a server reword breaks this
 * test rather than silently un-marking the field in the editor.
 */
describe('conflictField', () => {
  it('names the field a duplicate unique value belongs to', () => {
    const detail = "'email' must be unique; 'ada@example.com' is already taken";
    expect(conflictField(detail, ['name', 'email'])).toBe('email');
  });

  it('refuses to attribute a unique complaint to a key this type lacks', () => {
    const detail = "'sku' must be unique; 'A-1' is already taken";
    expect(conflictField(detail, ['name', 'email'])).toBeNull();
  });

  it('attributes a taken slug to the slug input', () => {
    const detail = "slug 'acme' is already used by another company record in 'en'";
    expect(conflictField(detail, ['name'])).toBe('slug');
  });

  it('leaves a conflict no single input owns unattributed', () => {
    const reindexing =
      "'email' is being reindexed, so its uniqueness cannot be checked; writes to this type are refused until the rebuild completes";
    expect(conflictField(reindexing, ['email'])).toBeNull();
    expect(
      conflictField("a company record in 'de' already exists in that translation group", ['name']),
    ).toBeNull();
  });
});

describe('humanizeCollisionDetail — U15: the wire key gives way to the label', () => {
  it('substitutes the field label into a unique-collision sentence', () => {
    const detail = "'ticket_code' must be unique; 'TK-1001' is already taken";
    expect(humanizeCollisionDetail(detail, 'Ticket code', 'QA UX Event')).toBe(
      "'Ticket code' must be unique; 'TK-1001' is already taken",
    );
  });

  it('substitutes the type label into a slug-collision sentence', () => {
    const detail = "slug 'acme' is already used by another qa_ux_event record in 'en'";
    expect(humanizeCollisionDetail(detail, null, 'QA UX Event')).toBe(
      "slug 'acme' is already used by another QA UX Event record in 'en'",
    );
  });

  it('leaves an unrecognised detail unchanged', () => {
    const detail = "a company record in 'de' already exists in that translation group";
    expect(humanizeCollisionDetail(detail, null, 'Company')).toBe(detail);
  });

  it('leaves a unique-collision sentence unchanged when no field label is known', () => {
    const detail = "'sku' must be unique; 'A-1' is already taken";
    expect(humanizeCollisionDetail(detail, null, 'Product')).toBe(detail);
  });
});
