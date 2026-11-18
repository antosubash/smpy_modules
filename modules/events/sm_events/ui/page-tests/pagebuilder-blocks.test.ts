import { describe, expect, it, vi } from 'vitest';

describe('pagebuilder-blocks', () => {
  it('registers UpcomingEvents and EventsCalendar in the events group, by catalogue key', async () => {
    const { registeredBlocks } = await import('@simple-module-py/pagebuilder');
    await import('../../pagebuilder-blocks');
    // Each block has its own guarded registration, so a clash on one name cannot leave the
    // other unregistered.
    for (const name of ['UpcomingEvents', 'EventsCalendar']) {
      const mine = registeredBlocks().find((r) => name in r.blocks);
      expect(mine, name).toBeDefined();
      expect(mine?.category).toEqual({ key: 'events', title: 'events.blocks.palette_group' });
      expect(mine?.layout).toBeFalsy(); // page-only: a list in the header would repeat everywhere
    }
  });

  it('a second import that registers again does not throw out of the module', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.resetModules();
    await expect(import('../../pagebuilder-blocks')).resolves.toBeDefined();
    warn.mockRestore();
  });
});
