// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { act, click, mount, setValue } from '../test-dom';
import type { GroupItem } from '../utils/types';
import { collection, flush, image, stubFetch } from './support';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));

const { GroupsTab } = await import('../components/groups/GroupsTab');
const Image = (await import('../pages/Image')).default;

const LIST = 'GET /api/images/collections/c1/groups';

function group(overrides: Partial<GroupItem> = {}): GroupItem {
  return {
    id: 'g1',
    collection_id: 'c1',
    key: 'site-1',
    name: null,
    description: null,
    image_count: 0,
    members: [],
    ...overrides,
  };
}

const input = (view: { find: <T extends Element>(s: string) => T | null }, selector: string) =>
  view.find<HTMLInputElement>(selector) as HTMLInputElement;

afterEach(() => vi.unstubAllGlobals());

describe('Groups tab: managing groups', () => {
  it('creates a group and shows the list the server answers with', async () => {
    let created = false;
    const calls = stubFetch({
      [LIST]: () => ({ items: created ? [group()] : [], next_cursor: null }),
      'POST /api/images/collections/c1/groups': () => {
        created = true;
        return group();
      },
    });
    const view = await mount(<GroupsTab collectionId="c1" canEdit />);
    await flush();
    await click(view.find('[data-testid="images-group-new"]'));
    await setValue(input(view, '#images-group-key'), ' site-1 ');
    await click(view.find('[data-testid="images-group-submit"]'));
    await flush();
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ key: 'site-1', name: null });
    expect(view.all('[data-testid="images-group"]')).toHaveLength(1);
    expect(view.find('[data-testid="images-group-form"]')).toBeNull();
    await view.unmount();
  });

  it('keeps the form open and shows the failure', async () => {
    stubFetch({
      [LIST]: { items: [], next_cursor: null },
      'POST /api/images/collections/c1/groups': () => {
        throw new Error('This collection already has a group with that key');
      },
    });
    const view = await mount(<GroupsTab collectionId="c1" canEdit />);
    await flush();
    await click(view.find('[data-testid="images-group-new"]'));
    await setValue(input(view, '#images-group-key'), 'dup');
    await click(view.find('[data-testid="images-group-submit"]'));
    await flush();
    expect(view.find('[data-testid="images-group-form"] [role="alert"]')).not.toBeNull();
    await view.unmount();
  });

  it('renames a group', async () => {
    const calls = stubFetch({
      [LIST]: { items: [group({ name: 'Old' })], next_cursor: null },
      'PATCH /api/images/groups/g1': () => group({ name: 'New' }),
    });
    const view = await mount(<GroupsTab collectionId="c1" canEdit />);
    await flush();
    await click(view.find('[data-testid="images-group-edit"]'));
    await setValue(input(view, '#images-group-name'), 'New');
    await click(view.find('[data-testid="images-group-submit"]'));
    await flush();
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ key: 'site-1', name: 'New' });
    await view.unmount();
  });

  it('offers no group controls to a viewer', async () => {
    stubFetch({ [LIST]: { items: [group()], next_cursor: null } });
    const view = await mount(<GroupsTab collectionId="c1" canEdit={false} />);
    await flush();
    for (const id of ['group-new', 'group-edit', 'group-delete', 'regroup-open']) {
      expect(view.find(`[data-testid="images-${id}"]`)).toBeNull();
    }
    await view.unmount();
  });
});

describe('Groups tab: a big regroup is a job', () => {
  afterEach(() => vi.useRealTimers());

  it('shows the job progress and refreshes the list when it finishes', async () => {
    vi.useFakeTimers();
    const settle = () => act(async () => vi.advanceTimersByTimeAsync(0));
    let reads = 0;
    const job = (status: string, scanned: number) => ({
      id: 'j1',
      collection_id: 'c1',
      status,
      error_code: null,
      pattern: 'p',
      reassign: false,
      dry_run: false,
      created_at: null,
      finished_at: null,
      scanned,
      matched: scanned,
      no_match: 0,
      timed_out: 0,
      already_grouped: 0,
      unchanged: 0,
      assigned: scanned,
      groups_created: 2,
      groups_existing: 0,
    });
    stubFetch({
      [LIST]: { items: [], next_cursor: null },
      'POST /api/images/collections/c1/regroup': { job_id: 'j1' },
      'GET /api/images/regroups/j1': () => (++reads === 1 ? job('running', 500) : job('completed', 1200)),
    });
    const onChanged = vi.fn();
    const view = await mount(<GroupsTab collectionId="c1" canEdit onChanged={onChanged} />);
    await settle();
    await click(view.find('[data-testid="images-regroup-open"]'));
    await setValue(input(view, '#images-regroup-pattern'), '(?P<group>x)');
    await click(view.find('[data-testid="images-regroup-apply"]'));
    await settle();
    expect(view.find('[data-testid="images-regroup-progress"]')?.textContent).toContain('500 images checked');
    expect(view.find('[data-testid="images-regroup-cancel"]')).not.toBeNull();
    expect(onChanged).not.toHaveBeenCalled();
    await act(async () => vi.advanceTimersByTimeAsync(2100));
    expect(view.find('[data-testid="images-regroup-progress"]')?.textContent).toContain('1200 images checked');
    expect(view.find('[data-testid="images-regroup-cancel"]')).toBeNull();
    expect(onChanged).toHaveBeenCalledOnce();
    await view.unmount();
  });
});

describe('Image page: group and role', () => {
  const props = { collection: collection(), can_view_original: false, can_manage: false };
  const groups = { items: [group({ id: 'g1', key: 'site-1' }), group({ id: 'g2', key: 'site-2' })], next_cursor: null };

  it('lets an editor move the image and choose a listed role', async () => {
    const calls = stubFetch({
      'GET /api/images/collections/c1/groups': groups,
      'PATCH /api/images/images/i1': () => image('i1', { group_id: 'g2', group_role: 'north' }),
    });
    const view = await mount(
      <Image image={image('i1')} can_edit group_roles={['point', 'north']} {...props} />,
    );
    await click(view.find('[data-testid="images-group-change"]'));
    await flush();
    await setValue(view.find<HTMLSelectElement>('#images-image-group-select') as HTMLSelectElement, 'g2');
    await setValue(view.find<HTMLSelectElement>('#images-image-role-select') as HTMLSelectElement, 'north');
    await click(view.find('[data-testid="images-group-save"]'));
    await flush();
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ group_id: 'g2', group_role: 'north' });
    expect(view.find('[data-testid="images-image-group-current"]')?.textContent).toBe('site-2 · north');
    await view.unmount();
  });

  it('takes a free-text role and can leave the group', async () => {
    const calls = stubFetch({
      'GET /api/images/collections/c1/groups': groups,
      'PATCH /api/images/images/i1': () => image('i1'),
    });
    const inGroup = image('i1', { group_id: 'g1', group_role: 'point' });
    const view = await mount(<Image image={inGroup} can_edit group_roles={['point']} {...props} />);
    await click(view.find('[data-testid="images-group-change"]'));
    await flush();
    await setValue(view.find<HTMLSelectElement>('#images-image-role-select') as HTMLSelectElement, '\u0000custom');
    await setValue(input(view, '[data-testid="images-role-custom"]'), 'Left bank');
    await click(view.find('[data-testid="images-group-save"]'));
    await flush();
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ group_id: 'g1', group_role: 'Left bank' });
    await click(view.find('[data-testid="images-group-change"]'));
    await flush();
    await setValue(view.find<HTMLSelectElement>('#images-image-group-select') as HTMLSelectElement, '');
    await click(view.find('[data-testid="images-group-save"]'));
    await flush();
    expect(calls.filter((c) => c.method === 'PATCH')[1].body).toEqual({ group_id: null });
    await view.unmount();
  });

  it('shows the group but no controls to someone who cannot edit', async () => {
    const calls = stubFetch({});
    const inGroup = image('i1', { group_id: 'g1', group_role: 'point', group_key: 'site-1' });
    const view = await mount(<Image image={inGroup} can_edit={false} {...props} />);
    expect(view.find('[data-testid="images-image-group-current"]')?.textContent).toBe('site-1 · point');
    expect(view.find('[data-testid="images-group-change"]')).toBeNull();
    expect(calls).toHaveLength(0);
    await view.unmount();
  });
});
