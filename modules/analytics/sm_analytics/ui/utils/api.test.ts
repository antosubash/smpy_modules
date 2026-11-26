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
  'redirects an expired session on a %s read to sign-in with a return URL',
  async (kind) => {
    window.history.replaceState({}, '', '/analytics/?range=week');
    const assign = vi.spyOn(window.location, 'assign').mockImplementation(() => {});
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
    expect(assign).toHaveBeenCalledWith('/users/login?next=%2Fanalytics%2F%3Frange%3Dweek');
  },
);
