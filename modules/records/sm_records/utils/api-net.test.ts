import { describe, expect, it } from 'vitest';

import { messageFor } from './api-net';

describe('messageFor — U34: a 5xx reads as a sentence, not a status line', () => {
  it('replaces the raw status line with a plain-language message for a 500 with no usable body', () => {
    expect(messageFor(500, 'Internal Server Error', null)).not.toContain('Request failed');
    expect(messageFor(500, 'Internal Server Error', null)).toContain('went wrong on the server');
  });

  it('does the same for any 5xx, and for a body that carries no errors/detail', () => {
    expect(messageFor(503, 'Service Unavailable', {})).toContain('went wrong on the server');
    expect(messageFor(502, 'Bad Gateway', null)).toContain('went wrong on the server');
  });

  it('still prefers a real detail or errors list when the 5xx body actually has one', () => {
    expect(messageFor(500, 'Internal Server Error', { detail: 'db unavailable' })).toBe(
      'db unavailable',
    );
    expect(
      messageFor(500, 'Internal Server Error', {
        errors: [{ field: 'title', message: 'too long' }],
      }),
    ).toBe('title: too long');
  });

  it('keeps the raw status-line fallback for a 4xx this build does not otherwise recognise', () => {
    expect(messageFor(418, "I'm a teapot", null)).toBe("Request failed (418 I'm a teapot)");
  });

  it('still answers 401 with the session-expired message, unaffected by the 5xx branch', () => {
    expect(messageFor(401, 'Unauthorized', null)).toContain('session has expired');
  });
});
