// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { click, mount, setValue } from './test-dom';
import type { GroupItem } from '../utils/types';
import { flush, image, stubFetch } from './support';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));

const { GroupsTab } = await import('../components/groups/GroupsTab');

const LIST = 'GET /api/images/collections/c1/groups';

function group(overrides: Partial<GroupItem> = {}): GroupItem {
  return {
    id: 'g1',
    collection_id: 'c1',
    key: 'site-1',
    name: null,
    description: null,
    image_count: 2,
    members: [
      image('i1', { group_id: 'g1', group_role: 'point' }),
      image('i2', { group_id: 'g1', group_role: 'north' }),
    ],
    ...overrides,
  };
}

afterEach(() => vi.unstubAllGlobals());

describe('Groups tab', () => {
  it('lists members in the order the server sent, with their roles', async () => {
    stubFetch({ [LIST]: { items: [group()], next_cursor: null } });
    const view = await mount(<GroupsTab collectionId="c1" canEdit />);
    await flush();
    const roles = view.all('[data-testid="images-group-member"]').map((m) => m.getAttribute('data-role'));
    expect(roles).toEqual(['point', 'north']);
    expect(view.find('[data-testid="images-group"]')?.textContent).toContain('site-1');
    await view.unmount();
  });

  it('says how many members are not shown', async () => {
    stubFetch({ [LIST]: { items: [group({ image_count: 11 })], next_cursor: null } });
    const view = await mount(<GroupsTab collectionId="c1" canEdit />);
    await flush();
    expect(view.find('[data-testid="images-group"]')?.textContent).toContain('+9 more');
    await view.unmount();
  });

  it('hides every control from someone who cannot edit', async () => {
    stubFetch({ [LIST]: { items: [group()], next_cursor: null } });
    const view = await mount(<GroupsTab collectionId="c1" canEdit={false} />);
    await flush();
    expect(view.find('[data-testid="images-regroup-open"]')).toBeNull();
    expect(view.find('[data-testid="images-group-delete"]')).toBeNull();
    await view.unmount();
  });

  it('previews a regroup without writing, then applies it', async () => {
    const sent: unknown[] = [];
    const answer = (call: { body: unknown }) => {
      sent.push(call.body);
      return {
        dry_run: (call.body as { dry_run: boolean }).dry_run,
        scanned: 5,
        matched: 4,
        no_match: 1,
        timed_out: 0,
        already_grouped: 0,
        unchanged: 0,
        assigned: 4,
        groups_created: 2,
      };
    };
    stubFetch({
      [LIST]: { items: [], next_cursor: null },
      'POST /api/images/collections/c1/regroup': answer,
    });
    const onChanged = vi.fn();
    const view = await mount(<GroupsTab collectionId="c1" canEdit onChanged={onChanged} />);
    await flush();
    await click(view.find('[data-testid="images-regroup-open"]'));
    await setValue(view.find<HTMLInputElement>('#images-regroup-pattern') as HTMLInputElement, '(?P<group>x)');
    await click(view.find('[data-testid="images-regroup-preview"]'));
    await flush();
    expect(view.find('[data-testid="images-regroup-result"]')?.textContent).toContain('4 of 5');
    expect(onChanged).not.toHaveBeenCalled();
    await click(view.find('[data-testid="images-regroup-apply"]'));
    await flush();
    expect(sent).toEqual([
      { pattern: '(?P<group>x)', reassign: false, dry_run: true },
      { pattern: '(?P<group>x)', reassign: false, dry_run: false },
    ]);
    expect(onChanged).toHaveBeenCalledOnce();
    await view.unmount();
  });
});
