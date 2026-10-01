import { describe, expect, it } from 'vitest';
import { seatsLabel } from './seats';

describe('seatsLabel', () => {
  it('uses the singular for one member on an unlimited plan', () => {
    expect(seatsLabel(1, null)).toBe('1 member');
  });

  it('uses the plural for zero or many members on an unlimited plan', () => {
    expect(seatsLabel(0, null)).toBe('0 members');
    expect(seatsLabel(3, null)).toBe('3 members');
  });

  it('shows usage against a seat limit', () => {
    expect(seatsLabel(2, 5)).toBe('2 of 5 seats used');
  });

  it('uses the singular for a one-seat limit', () => {
    expect(seatsLabel(1, 1)).toBe('1 of 1 seat used');
    expect(seatsLabel(0, 1)).toBe('0 of 1 seat used');
  });
});
