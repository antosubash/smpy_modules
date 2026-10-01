// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';

import { act, mount } from '../test-dom';
import type { TypeRead } from '../utils/types';
import { useTypeSync } from './useTypeSync';

function type(version: number, overrides: Partial<TypeRead> = {}): TypeRead {
  return {
    key: 'book',
    label: 'Book',
    label_plural: 'Books',
    fields: [],
    version,
    reindex_pending: {},
    ...overrides,
  } as unknown as TypeRead;
}

type Sync = ReturnType<typeof useTypeSync>;

function Probe({
  type: prop,
  dirty,
  onRender,
}: {
  type: TypeRead;
  dirty: boolean;
  onRender: (s: Sync) => void;
}) {
  const sync = useTypeSync(prop);
  sync.dirtyRef.current = dirty;
  onRender(sync);
  return null;
}

async function mountSync(initial: TypeRead, dirty: boolean) {
  let latest: Sync | null = null;
  const view = await mount(
    <Probe
      type={initial}
      dirty={dirty}
      onRender={(s) => {
        latest = s;
      }}
    />,
  );
  const push = async (next: TypeRead, nextDirty: boolean) => {
    await view.render(
      <Probe
        type={next}
        dirty={nextDirty}
        onRender={(s) => {
          latest = s;
        }}
      />,
    );
  };
  return { view, push, sync: () => latest as unknown as Sync };
}

describe('useTypeSync — R15: a reindex poll may not re-baseline the version', () => {
  it('keeps the draft on the version it was opened against, and says the type changed', async () => {
    const opened = type(4);
    const { view, push, sync } = await mountSync(opened, true);
    expect(sync().current?.version).toBe(4);

    // The poll comes back with someone else's save on top of it.
    await push(type(5, { label: 'Renamed', reindex_pending: { title: 'now' } }), true);

    // `current.version` is what Save sends as `expected_version`: adopting 5
    // here is what silently overwrote the other editor.
    expect(sync().current?.version).toBe(4);
    expect(sync().current?.label).toBe('Book');
    // …but the thing the poll went to fetch is taken.
    expect(sync().current?.reindex_pending).toEqual({ title: 'now' });
    // …and the conflict UI has something to render.
    expect(sync().externalChange?.version).toBe(5);
    await view.unmount();
  });

  it('adopts a newer type silently when the draft is clean', async () => {
    const { view, push, sync } = await mountSync(type(4), false);
    await push(type(5, { label: 'Renamed' }), false);
    expect(sync().current?.version).toBe(5);
    expect(sync().current?.label).toBe('Renamed');
    expect(sync().externalChange).toBeNull();
    await view.unmount();
  });

  it('still follows a same-version poll, so the reindex banner clears (F4)', async () => {
    const { view, push, sync } = await mountSync(
      type(4, { reindex_pending: { title: 'now' } }),
      true,
    );
    await push(type(4, { reindex_pending: {} }), true);
    expect(sync().current?.reindex_pending).toEqual({});
    expect(sync().externalChange).toBeNull();
    await view.unmount();
  });

  it('clears the notice once the newer type is adopted', async () => {
    const { view, push, sync } = await mountSync(type(4), true);
    await push(type(5), true);
    expect(sync().externalChange?.version).toBe(5);

    // "Reload" on the conflict notice hands the server's copy to `adopt`.
    await act(async () => {
      sync().adopt(type(5, { label: 'Renamed' }));
    });
    expect(sync().externalChange).toBeNull();
    expect(sync().current?.version).toBe(5);
    await view.unmount();
  });
});
