import { describe, expect, it } from 'vitest';

import { errorFrom } from '../modules/news/news/utils/http';
import { errorMessage } from '../modules/pagebuilder/pagebuilder/utils/request';

/**
 * News' `errorFrom` and pagebuilder's `errorMessage` are copies (#127): both
 * turn a failed response from the same backend into the sentence an author
 * sees. They cannot share code — a published module must not import a sibling —
 * and their shapes differ (news returns an error carrying the status), so
 * `scripts/tests/parity_families.py` cannot compare their source. This compares
 * what they say instead, for every branch they share.
 *
 * Not covered on purpose: a 422 whose entries have a Pydantic `type` news words
 * itself (`string_too_long`, `missing`, …). That is news' `describeError`, a
 * wording upgrade pagebuilder has not adopted, and the family file says so.
 */

function response(body: string, status = 400, statusText = 'Bad Request', type = 'application/json') {
  return new Response(body, { status, statusText, headers: { 'content-type': type } });
}

const CASES: [string, () => Response][] = [
  ['an empty body', () => response('', 500, 'Internal Server Error')],
  ['a string detail', () => response('{"detail":"Slug already in use."}', 409, 'Conflict')],
  ['a blank detail', () => response('{"detail":"   "}')],
  [
    'a CSRF refusal',
    () => response('{"detail":"CSRF token missing or invalid."}', 403, 'Forbidden'),
  ],
  ['a 403 that is not a CSRF refusal', () => response('{"detail":"Not allowed"}', 403, 'Forbidden')],
  [
    'an untyped 422 list',
    () => response('{"detail":[{"loc":["body","title"],"msg":"too odd"}]}', 422, 'Unprocessable'),
  ],
  ['a 422 list without a field', () => response('{"detail":[{"msg":"bad body"}]}', 422, 'Bad')],
  [
    'an HTML shell',
    () => response('<!DOCTYPE html><html></html>', 404, 'Not Found', 'text/html'),
  ],
  ['JSON with no detail', () => response('{"error":"x"}')],
  ['a JSON array', () => response('[1, 2]')],
  ['plain text', () => response('upstream timed out', 502, 'Bad Gateway', 'text/plain')],
  ['a long plain text', () => response('x'.repeat(500), 502, 'Bad Gateway', 'text/plain')],
];

describe('news errorFrom and pagebuilder errorMessage say the same thing', () => {
  it.each(CASES)('for %s', async (_, make) => {
    const news = await errorFrom(make());
    const pagebuilder = await errorMessage(make());
    expect(news.message).toBe(pagebuilder);
  });
});
