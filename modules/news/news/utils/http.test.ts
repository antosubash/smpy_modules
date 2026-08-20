import { describe, expect, it } from 'vitest';

import { errorFrom, fromValidationErrors } from './http';

/**
 * FastAPI answers a bad field with 422 and a *list* of Pydantic errors. The
 * old code stringified that list, so typing a space into a URL field produced
 * `[{"type":"string_pattern_mismatch","loc":["body","slug"],…}]` on screen.
 */

const PYDANTIC_SLUG_ERROR = [
  {
    type: 'string_pattern_mismatch',
    loc: ['body', 'slug'],
    msg: "String should match pattern '^[a-z0-9][a-z0-9-]*$'",
    input: 'Not A Slug',
  },
];

function response(
  body: string,
  { status = 400, statusText = 'Bad Request', contentType = 'application/json' } = {},
): Response {
  return new Response(body, { status, statusText, headers: { 'content-type': contentType } });
}

const INERTIA_SHELL =
  '<!DOCTYPE html><html><body><div id="app" data-page="{&quot;permissions&quot;:[]}"></div></body></html>';

/**
 * The same six cases `pagebuilder/utils/request.test.ts` asserts. The two
 * helpers are deliberate siblings; these tests are what stops them drifting
 * apart again, which has now happened twice.
 */
describe('errorFrom — matching pagebuilder/utils/request.ts', () => {
  it('prefers the API detail', async () => {
    expect((await errorFrom(response('{"detail":"Slug already in use."}'))).message).toBe(
      'Slug already in use.',
    );
  });

  it('turns a 422 validation list into a sentence', async () => {
    const body = JSON.stringify({ detail: [{ loc: ['body', 'slug'], msg: 'is required' }] });

    expect(
      (await errorFrom(response(body, { status: 422, statusText: 'Unprocessable Entity' })))
        .message,
    ).toBe('slug: is required');
  });

  it('never renders an HTML body, whatever the content-type claims', async () => {
    for (const contentType of ['text/html', 'application/json']) {
      const message = (
        await errorFrom(
          response(INERTIA_SHELL, { status: 404, statusText: 'Not Found', contentType }),
        )
      ).message;
      expect(message).toBe('Request failed (404 Not Found)');
      expect(message).not.toContain('data-page');
    }
  });

  it('reads a JSON detail even when the response mislabels its content-type', async () => {
    expect(
      (await errorFrom(response('{"detail":"Still in use."}', { contentType: 'text/plain' })))
        .message,
    ).toBe('Still in use.');
  });

  it('falls back to the status for an empty body', async () => {
    expect(
      (await errorFrom(response('', { status: 500, statusText: 'Server Error' }))).message,
    ).toBe('Request failed (500 Server Error)');
  });

  it('shows a short plain-text body, clamped', async () => {
    const message = (await errorFrom(response('x'.repeat(500), { contentType: 'text/plain' })))
      .message;

    expect(message.startsWith('Request failed (400 Bad Request): ')).toBe(true);
    expect(message.length).toBeLessThan(260);
  });
});

describe('fromValidationErrors', () => {
  it('names the field and says what is wrong', () => {
    expect(fromValidationErrors(PYDANTIC_SLUG_ERROR)).toBe(
      "slug: String should match pattern '^[a-z0-9][a-z0-9-]*$'",
    );
  });

  it('drops the "body" wrapper, which means nothing to the reader', () => {
    expect(fromValidationErrors(PYDANTIC_SLUG_ERROR)).not.toContain('body');
  });

  it('joins several field errors', () => {
    const both = [
      { loc: ['body', 'slug'], msg: 'is required' },
      { loc: ['body', 'title'], msg: 'is too long' },
    ];

    expect(fromValidationErrors(both)).toBe('slug: is required; title: is too long');
  });

  it('drops list indices from the path', () => {
    const nested = [{ loc: ['body', 'tags', 0], msg: 'is too long' }];

    expect(fromValidationErrors(nested)).toBe('tags: is too long');
  });

  it('falls back when an entry carries no message', () => {
    expect(fromValidationErrors([{ loc: ['body', 'slug'] }])).toBe('slug: is not valid');
  });

  it('returns null for anything that is not a validation list', () => {
    // The caller then uses the string detail or the status line instead.
    expect(fromValidationErrors('already in use')).toBeNull();
    expect(fromValidationErrors(undefined)).toBeNull();
    expect(fromValidationErrors([])).toBeNull();
    expect(fromValidationErrors({ detail: 'x' })).toBeNull();
  });
});
