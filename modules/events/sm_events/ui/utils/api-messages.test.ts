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

it.each([
  ['invalid_registration', 422, 'registration settings are not valid'],
  ['registration_unavailable', 422, 'not available'],
  ['unknown_registration_target', 422, 'does not exist'],
  ['registrations_orphaned', 409, 'already has registrations'],
  ['registration_has_seats', 409, 'already registered'],
  ['seats_busy', 409, 'try again'],
  ['registration_closes_before_opens', 422, 'close after it opens'],
  ['registration_time_invalid', 422, 'valid date and time'],
  ['registration_url_required', 422, 'registration link'],
  ['registration_target_required', 422, 'registration form'],
  ['registration_provider_required', 422, 'kind of registration'],
  ['registration_reminder_invalid', 422, 'reminder times'],
  ['registration_option_not_allowed', 422, 'does not apply'],
])("words the registration code %s in the reader's language", async (code, status, words) => {
  const { errorText } = await import('./api');
  expect(errorText(new ApiError(status, code))).toContain(words);
});
