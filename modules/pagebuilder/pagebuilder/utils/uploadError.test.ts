import { describe, expect, it } from 'vitest';

import en from '../locales/en.json';
import { UploadError, uploadErrorMessage, uploadNetworkError, uploadRejected } from './uploadError';

describe('uploadErrorMessage', () => {
  it('maps 415 to a translated sentence, not the response body', () => {
    const message = uploadErrorMessage(415);
    expect(message).toBe(en.errors.upload_unsupported);
    expect(message).not.toContain('415');
  });

  it('maps 413 to the too-large message', () => {
    expect(uploadErrorMessage(413)).toBe(en.errors.upload_too_large);
  });

  it('maps 401 and 403 to the permission message', () => {
    expect(uploadErrorMessage(403)).toBe(en.errors.upload_forbidden);
    expect(uploadErrorMessage(401)).toBe(en.errors.upload_forbidden);
  });

  it('maps 422 to the translated validation sentence, with no server prose', () => {
    // The server's Pydantic `msg` ("Field required") is English in every
    // console language, so it is never part of the message.
    const message = uploadErrorMessage(422);
    expect(message).toBe(en.errors.upload_failed_invalid);
    expect(message).not.toContain('Field required');
    expect(message).not.toContain('{');
  });

  it('falls back to the generic message with the status otherwise', () => {
    expect(uploadErrorMessage(500)).toBe('Upload failed (500)');
    expect(uploadErrorMessage(502)).toBe('Upload failed (502)');
  });
});

describe('UploadError factories', () => {
  it('carries the status and the translated message', () => {
    const err = uploadRejected(415);
    expect(err).toBeInstanceOf(UploadError);
    expect(err.status).toBe(415);
    expect(err.message).toBe(en.errors.upload_unsupported);
  });

  it('says "too many pixels" for a 413 carrying that code, not "too large" (#221)', () => {
    const body = JSON.stringify({
      detail: { code: 'image_too_many_pixels', message: 'Image dimensions exceed the pixel limit' },
    });
    const err = uploadRejected(413, body);
    expect(err.status).toBe(413);
    expect(err.message).toBe(en.errors.upload_too_many_pixels);
    expect(err.message).not.toContain('Image dimensions');
  });

  it('keeps the byte-size message for a plain 413 or an unreadable body', () => {
    expect(uploadRejected(413, '{"detail":"File exceeds 10 bytes"}').message).toBe(
      en.errors.upload_too_large,
    );
    expect(uploadRejected(413, '<html>').message).toBe(en.errors.upload_too_large);
    expect(uploadRejected(413).message).toBe(en.errors.upload_too_large);
  });

  it('uses the translated network message, not the browser text', () => {
    const err = uploadNetworkError();
    expect(err).toBeInstanceOf(UploadError);
    expect(err.status).toBeNull();
    expect(err.message).toBe(en.errors.upload_network);
  });
});
