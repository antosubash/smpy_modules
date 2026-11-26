// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest';
import { geoStatus, listProperties, loadReport, saveProperty } from './api';

const input = {
  name: 'Site',
  kind: 'public' as const,
  origins: ['https://example.com'],
  route_patterns: ['/p/:slug'],
  event_allowlist: {},
  utm_parameters: [],
  enabled: true,
};
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
it('retains nested 422 field paths and removes the pydantic prefix', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      Response.json(
        {
          detail: [
            {
              loc: ['body', 'origins', 0],
              msg: 'Value error, Expected an exact http(s) origin without a path',
              type: 'value_error',
            },
            {
              loc: ['body', 'route_patterns'],
              msg: 'Value error, Route patterns must start with /',
              type: 'value_error',
            },
          ],
        },
        { status: 422 },
      ),
    ),
  );
  await expect(saveProperty(input)).rejects.toMatchObject({
    status: 422,
    fieldErrors: {
      origins: 'Expected an exact http(s) origin without a path',
      route_patterns: 'Route patterns must start with /',
    },
  });
});
it.each(['list', 'geo', 'report'])(
  'reloads the protected page after a %s 401 so the framework preserves the return URL',
  async (kind) => {
    window.history.replaceState({}, '', '/analytics/?range=week');
    const assign = vi.spyOn(window.location, 'assign').mockImplementation(() => {});
    const reload = vi.spyOn(window.location, 'reload').mockImplementation(() => {});
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Response.json({ detail: 'Not authenticated' }, { status: 401 })),
    );
    const call =
      kind === 'list'
        ? listProperties()
        : kind === 'geo'
          ? geoStatus()
          : loadReport('one', {
              start: '',
              end: '',
              path: '',
              event: '',
              country: '',
              region: '',
              city: '',
            });
    await expect(call).rejects.toMatchObject({ status: 401 });
    expect(reload).toHaveBeenCalledOnce();
    expect(assign).not.toHaveBeenCalled();
    expect(window.location.pathname + window.location.search).toBe('/analytics/?range=week');
  },
);

it('does not reload the login page if a pending API read returns 401 there', async () => {
  window.history.replaceState({}, '', '/users/login');
  const reload = vi.spyOn(window.location, 'reload').mockImplementation(() => {});
  const assign = vi.spyOn(window.location, 'assign').mockImplementation(() => {});
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Response.json({ detail: 'Not authenticated' }, { status: 401 })),
  );
  await expect(listProperties()).rejects.toMatchObject({ status: 401 });
  expect(reload).not.toHaveBeenCalled();
  expect(assign).not.toHaveBeenCalled();
});

it('does not redirect when a canceled read returns an expired-session response', async () => {
  const assign = vi.spyOn(window.location, 'assign').mockImplementation(() => {});
  const reload = vi.spyOn(window.location, 'reload').mockImplementation(() => {});
  let finish = (_response: Response) => {};
  vi.stubGlobal(
    'fetch',
    vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve;
        }),
    ),
  );
  const controller = new AbortController();
  const request = listProperties(controller.signal);
  const rejected = expect(request).rejects.toMatchObject({ name: 'AbortError' });
  finish(Response.json({ detail: 'Not authenticated' }, { status: 401 }));
  controller.abort();
  await rejected;
  expect(assign).not.toHaveBeenCalled();
  expect(reload).not.toHaveBeenCalled();
});
