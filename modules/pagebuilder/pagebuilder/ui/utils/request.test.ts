import { describe, expect, it } from 'vitest';

import { errorMessage, fromValidationErrors } from './request';

/**
 * The rule these guard: a failed request must never render the response body
 * as prose. Admin routes answer 404 with the Inertia HTML shell, and echoing
 * it put the permissions list, the i18n catalogue and the menu JSON on screen
 * as the error text of a media asset that did not exist.
 */

function response(
  body: string,
  { status = 400, statusText = 'Bad Request', contentType = 'application/json' } = {},
): Response {
  return new Response(body, {
    status,
    statusText,
    headers: { 'content-type': contentType },
  });
}

const INERTIA_SHELL =
  '<!DOCTYPE html><html><body><div id="app" data-page="{&quot;props&quot;:{&quot;permissions&quot;:[&quot;news.edit&quot;]}}"></div></body></html>';

describe('errorMessage', () => {
  it('prefers the API detail', async () => {
    expect(await errorMessage(response('{"detail":"Slug already in use."}'))).toBe(
      'Slug already in use.',
    );
  });

  it('never renders an HTML body, whatever the content-type claims', async () => {
    const asHtml = await errorMessage(
      response(INERTIA_SHELL, { status: 404, statusText: 'Not Found', contentType: 'text/html' }),
    );
    const mislabelled = await errorMessage(
      response(INERTIA_SHELL, {
        status: 404,
        statusText: 'Not Found',
        contentType: 'application/json',
      }),
    );

    for (const message of [asHtml, mislabelled]) {
      expect(message).toBe('Request failed (404 Not Found)');
      expect(message).not.toContain('data-page');
      expect(message).not.toContain('permissions');
    }
  });

  it('reads a JSON detail even when the response mislabels its content-type', async () => {
    // The parse is attempted regardless — throwing away a good message because
    // a header was wrong helps nobody.
    expect(
      await errorMessage(response('{"detail":"Still in use."}', { contentType: 'text/plain' })),
    ).toBe('Still in use.');
  });

  it('turns a 422 validation list into a sentence', async () => {
    const body = JSON.stringify({
      detail: [{ loc: ['body', 'slug'], msg: 'String should match pattern' }],
    });

    expect(
      await errorMessage(response(body, { status: 422, statusText: 'Unprocessable Entity' })),
    ).toBe('slug: String should match pattern');
  });

  it('falls back to the status for an empty body', async () => {
    expect(await errorMessage(response('', { status: 500, statusText: 'Server Error' }))).toBe(
      'Request failed (500 Server Error)',
    );
  });

  it('shows a short plain-text body, clamped', async () => {
    const long = 'x'.repeat(500);
    const message = await errorMessage(response(long, { contentType: 'text/plain' }));

    expect(message.startsWith('Request failed (400 Bad Request): ')).toBe(true);
    expect(message.length).toBeLessThan(260);
  });
});

describe('fromValidationErrors', () => {
  it('names the field and drops the body wrapper and list indices', () => {
    expect(fromValidationErrors([{ loc: ['body', 'tags', 0], msg: 'is too long' }])).toBe(
      'tags: is too long',
    );
  });

  it('joins several errors', () => {
    expect(
      fromValidationErrors([
        { loc: ['body', 'slug'], msg: 'is required' },
        { loc: ['body', 'title'], msg: 'is too long' },
      ]),
    ).toBe('slug: is required; title: is too long');
  });

  it('returns null for anything that is not a validation list', () => {
    expect(fromValidationErrors('already in use')).toBeNull();
    expect(fromValidationErrors([])).toBeNull();
    expect(fromValidationErrors(undefined)).toBeNull();
  });
});
