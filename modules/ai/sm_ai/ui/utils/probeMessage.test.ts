import { describe, expect, it } from 'vitest';

import { translate } from './i18n';
import { probeMessage } from './probeMessage';

describe('probeMessage', () => {
  it('translates every code the API sends', () => {
    for (const code of [
      'base_url_refused',
      'not_configured',
      'key_unreadable',
      'unreachable',
      'connection_refused',
      'timeout',
      'unauthorised',
      'http_error',
      'other',
    ]) {
      const message = probeMessage(translate, { code, error: 'API text', status: 500 });
      expect(message).not.toBe('API text');
      expect(message).not.toContain('ai.probe');
    }
  });

  it('names the setting to turn on for a refused base URL', () => {
    expect(probeMessage(translate, { code: 'base_url_refused', error: '' })).toContain(
      'Allow private base URLs',
    );
  });

  it('puts the status into an HTTP failure', () => {
    expect(probeMessage(translate, { code: 'http_error', error: '', status: 502 })).toContain(
      'HTTP 502',
    );
  });

  it('falls back to the carried message without a known code', () => {
    expect(probeMessage(translate, { error: 'Failed to fetch' })).toBe('Failed to fetch');
    expect(probeMessage(translate, { code: 'new_code', error: 'x' })).toBe('x');
  });
});
