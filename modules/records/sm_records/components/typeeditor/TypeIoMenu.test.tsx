// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';

import { mount } from '../../test-dom';

const { TypeIoMenu } = await import('./TypeIoMenu');

// Driving the Radix `DropdownMenu` itself open to read the rendered item
// text is not exercised anywhere in this module's tests — see
// `RecordIoMenu.test.tsx`'s own note on why (`DropdownMenuContent` is not
// force-mounted, so its items are not in the DOM until it is actually
// opened, and this suite has no established pattern that does that
// reliably). This stays at the level the repro (`f5.mjs`) actually caught
// the regression at: the trigger itself was unreachable — `[data-testid=
// records-type-io-menu]` timed out on `/types/new` because the component
// returned `null` outright.
describe('TypeIoMenu — U4: importing a definition is reachable on the New-type screen', () => {
  it('renders the Definition menu when there is no current type yet', async () => {
    const view = await mount(
      <TypeIoMenu currentKey={null} pending={false} onImport={vi.fn(async () => undefined)} />,
    );
    expect(view.find('[data-testid="records-type-io-menu"]')).not.toBeNull();
    // The hidden file input `input.current?.click()` targets is what
    // actually drives Import — present regardless of whether the menu
    // itself can be opened here.
    expect(view.find('[data-testid="records-type-import-input"]')).not.toBeNull();
    await view.unmount();
  });

  it('still renders normally once a type exists', async () => {
    const view = await mount(
      <TypeIoMenu currentKey="book" pending={false} onImport={vi.fn(async () => undefined)} />,
    );
    expect(view.find('[data-testid="records-type-io-menu"]')).not.toBeNull();
    await view.unmount();
  });
});
