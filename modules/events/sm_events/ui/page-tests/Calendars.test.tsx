// @vitest-environment happy-dom

import { setCsrfToken } from '@simple-module-py/ui/lib/api';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Call } from './support';
import { button, calendar, field, flush, stubFetch, submit } from './support';
import { click, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
const { default: Calendars } = await import('../../pages/Calendars');
const API = '/api/events/calendars';
const props = { can_create: true, can_manage: false, user_id: 'u1', default_timezone: 'UTC' };

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(undefined);
  document.body.innerHTML = '';
});

describe('Calendars', () => {
  it('lists calendars with visibility badges, timezone and a foreign owner', async () => {
    stubFetch({
      [`GET ${API}`]: [
        calendar(),
        calendar({
          id: 'c2',
          name: 'Office',
          visibility: 'internal',
          owner_id: 'u2',
          owner_name: 'Erin Editor',
        }),
        calendar({ id: 'c3', name: 'Lectures', visibility: 'public' }),
      ],
    });
    const view = await mount(<Calendars {...props} />);
    await flush();
    expect(view.host.textContent).toContain('Private');
    expect(view.host.textContent).toContain('Internal');
    expect(view.host.textContent).toContain('Public');
    expect(view.host.textContent).toContain('Europe/Vienna');
    expect(view.host.textContent).toContain('Erin Editor');
    expect(view.host.textContent).not.toContain('u2');
    await view.unmount();
  });
  it('shows You, the owner name, or a neutral label - never an owner id', async () => {
    stubFetch({
      [`GET ${API}`]: [
        calendar({ id: 'c1', name: 'Mine' }),
        calendar({ id: 'c2', name: 'Named', owner_id: 'u2', owner_name: 'Erin Editor' }),
        calendar({ id: 'c3', name: 'Orphan', owner_id: 'gone-id', owner_name: null }),
      ],
    });
    const view = await mount(<Calendars {...props} />);
    await flush();
    const cells = (name: string) =>
      [...view.host.querySelectorAll('tr')]
        .find((row) => row.textContent?.includes(name))
        ?.querySelectorAll('td')[4]?.textContent;
    expect(cells('Mine')).toBe('You');
    expect(cells('Named')).toBe('Erin Editor');
    expect(cells('Orphan')).toBe('Unknown user');
    expect(view.host.textContent).not.toContain('gone-id');
    await view.unmount();
  });
  it('hides New calendar without can_create', async () => {
    stubFetch({ [`GET ${API}`]: [] });
    const view = await mount(<Calendars {...props} can_create={false} />);
    await flush();
    expect(view.button('New calendar')).toBeUndefined();
    await view.unmount();
  });
  it('creates a calendar and shows it with a CSRF header', async () => {
    let made = false;
    const calls = stubFetch({
      [`GET ${API}`]: () => (made ? [calendar()] : []),
      [`POST ${API}`]: (call: Call) => {
        made = true;
        return calendar(call.body as object);
      },
    });
    setCsrfToken('session-token');
    const view = await mount(<Calendars {...props} />);
    await flush();
    await click(button('New calendar'));
    await setValue(field('calendar-name'), 'Team');
    await setValue(field('calendar-timezone'), 'Europe/Vienna');
    await submit();
    const post = calls.find((c) => c.method === 'POST');
    expect(post?.body).toEqual({
      name: 'Team',
      color: '#2563eb',
      description: null,
      default_timezone: 'Europe/Vienna',
      visibility: 'private',
    });
    expect(post?.headers.get('X-CSRF-Token')).toBe('session-token');
    expect(view.host.textContent).toContain('Team');
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    await view.unmount();
  });
  it('shows the slug_taken message on 409 and keeps the form', async () => {
    stubFetch({
      [`GET ${API}`]: [],
      [`POST ${API}`]: Response.json({ detail: 'collision', code: 'slug_taken' }, { status: 409 }),
    });
    const view = await mount(<Calendars {...props} />);
    await flush();
    await click(button('New calendar'));
    await setValue(field('calendar-name'), 'Team');
    await submit();
    expect(document.querySelector('[role="alert"]')?.textContent).toContain(
      'slug is already in use',
    );
    expect(field('calendar-name').value).toBe('Team');
    await view.unmount();
  });
  it('offers Share, Visibility and Trash only when can_own and Edit when can_edit', async () => {
    stubFetch({ [`GET ${API}`]: [calendar({ can_own: false })] });
    const view = await mount(<Calendars {...props} />);
    await flush();
    expect(view.button('Edit')).toBeDefined();
    for (const text of ['Share', 'Visibility', 'Move to trash', 'Transfer ownership'])
      expect(view.button(text)).toBeUndefined();
    await view.unmount();
  });
  it('trash then restore, with confirmation and refetching', async () => {
    let trashed = false;
    const calls = stubFetch({
      [`GET ${API}`]: (call: Call) =>
        new URLSearchParams(call.url.split('?')[1]).get('trashed') === String(trashed)
          ? [calendar()]
          : [],
      [`DELETE ${API}/c1`]: () => {
        trashed = true;
        return null;
      },
      [`POST ${API}/c1/restore`]: () => {
        trashed = false;
        return calendar();
      },
    });
    const view = await mount(<Calendars {...props} />);
    await flush();
    await click(button('Move to trash'));
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false);
    const confirm = document.querySelector('[role="alertdialog"]');
    if (!confirm) throw new Error('Missing confirmation');
    await click(button('Move to trash', confirm));
    await flush();
    expect(view.host.textContent).not.toContain('Team');
    await click(button('Trash'));
    await flush();
    expect(view.host.textContent).toContain('Team');
    await click(button('Restore'));
    await flush();
    expect(calls.some((c) => c.url === `${API}/c1/restore` && c.method === 'POST')).toBe(true);
    await click(button('Active'));
    await flush();
    expect(view.host.textContent).toContain('Team');
    await view.unmount();
  });
  it('edits metadata without sending visibility', async () => {
    const calls = stubFetch({
      [`GET ${API}`]: [calendar()],
      [`PATCH ${API}/c1`]: calendar({ name: 'Renamed' }),
    });
    const view = await mount(<Calendars {...props} />);
    await flush();
    await click(button('Edit'));
    expect(document.getElementById('calendar-visibility')).toBeNull();
    await setValue(field('calendar-name'), 'Renamed');
    await submit();
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({
      name: 'Renamed',
      slug: 'team',
      color: '#2563eb',
      description: null,
      default_timezone: 'Europe/Vienna',
    });
    await view.unmount();
  });
  it('reports a failed list load', async () => {
    stubFetch({ [`GET ${API}`]: Response.json({ code: 'tenant_required' }, { status: 403 }) });
    const view = await mount(<Calendars {...props} />);
    await flush();
    expect(view.find('[role="alert"]')?.textContent).toContain('organisation');
    await view.unmount();
  });
});
