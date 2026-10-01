import { describe, expect, it, vi } from 'vitest';

vi.mock('@inertiajs/react', () => ({ router: { reload: vi.fn() }, Link: () => null }));

const { revisionEvent } = await import('./RecordRevisions');

/** A passthrough translator — every call resolves to its English default. */
function fakeT(key: string, opts?: Record<string, unknown>): string {
  return (opts?.defaultValue as string) ?? key;
}

describe('revisionEvent — R11: a revision says what happened, not `update`', () => {
  it('names the four RevisionEvent values (models/_record.py)', () => {
    expect(revisionEvent(fakeT, 'create')).toBe('Created');
    expect(revisionEvent(fakeT, 'update')).toBe('Updated');
    expect(revisionEvent(fakeT, 'delete')).toBe('Deleted');
    expect(revisionEvent(fakeT, 'restore')).toBe('Restored');
  });

  it('prints an event this build does not know as itself, rather than nothing', () => {
    expect(revisionEvent(fakeT, 'merged')).toBe('merged');
  });
});
