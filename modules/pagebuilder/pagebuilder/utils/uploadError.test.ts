import { describe, expect, it } from 'vitest';

import en from '../locales/en.json';
import { uploadErrorMessage } from './uploadError';

const RAW = '{"detail":"File contents do not match an allowed image format"}';

describe('uploadErrorMessage', () => {
  it('maps 415 to a translated sentence, not the response body', () => {
    const message = uploadErrorMessage(415, RAW);
    expect(message).toBe(en.errors.upload_unsupported);
    expect(message).not.toContain('{');
    expect(message).not.toContain('415');
  });

  it('maps 413 to the too-large message', () => {
    expect(uploadErrorMessage(413, '{"detail":"File exceeds 10485760 bytes"}')).toBe(
      en.errors.upload_too_large,
    );
  });

  it('maps 401 and 403 to the permission message', () => {
    expect(uploadErrorMessage(403, '')).toBe(en.errors.upload_forbidden);
    expect(uploadErrorMessage(401, '')).toBe(en.errors.upload_forbidden);
  });

  it('turns a 422 detail list into field messages', () => {
    const body = JSON.stringify({
      detail: [{ loc: ['body', 'folder'], msg: 'Field required', type: 'missing' }],
    });
    expect(uploadErrorMessage(422, body)).toBe('Upload failed: folder: Field required');
  });

  it('falls back to the generic message for a 422 without a list', () => {
    expect(uploadErrorMessage(422, '{"detail":"Folder path is too long"}')).toBe(
      'Upload failed (422)',
    );
  });

  it('never echoes a non-JSON body', () => {
    expect(uploadErrorMessage(500, '<!DOCTYPE html><html>boom</html>')).toBe('Upload failed (500)');
    expect(uploadErrorMessage(502, 'Bad Gateway')).toBe('Upload failed (502)');
  });
});
