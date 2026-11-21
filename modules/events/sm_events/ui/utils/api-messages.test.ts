// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest';
import { stubFetch } from '../page-tests/support';
import { ApiError, send } from './api';

afterEach(() => vi.unstubAllGlobals());

it('422 messages keyed by dotted loc', async () => {
  stubFetch({
    'PATCH /api/x': () =>
      new Response(
        JSON.stringify({
          detail: [
            { loc: ['body', 'extra', 'speaker'], msg: 'Field required', type: 'missing' },
            { loc: ['body', 'extra', 'nested', 0, 'a'], msg: 'Bad', type: 'value_error' },
          ],
        }),
        { status: 422, headers: { 'content-type': 'application/json' } },
      ),
  });
  const error = (await send('/api/x', { method: 'PATCH', json: {} }).catch(
    (e: unknown) => e,
  )) as ApiError;
  expect(error).toBeInstanceOf(ApiError);
  expect(error.fields).toEqual(['extra.speaker', 'extra.nested.0.a']);
  expect(error.messages).toEqual({
    'extra.speaker': 'Field required',
    'extra.nested.0.a': 'Bad',
  });
});

it('has no messages for another status', async () => {
  stubFetch({
    'PATCH /api/x': () =>
      new Response(JSON.stringify({ code: 'stale', detail: 'x' }), {
        status: 409,
        headers: { 'content-type': 'application/json' },
      }),
  });
  const error = (await send('/api/x', { method: 'PATCH', json: {} }).catch(
    (e: unknown) => e,
  )) as ApiError;
  expect(error.messages).toEqual({});
});
