import { describe, expect, it } from 'vitest';

import { fieldError, isReplyTo, toPatch } from './CampaignMeta';

describe('CampaignMeta toPatch', () => {
  it('leaves an invalid reply-to out of the PATCH', () => {
    expect(toPatch('reply_to', 'foo@', false)).toBeNull();
    expect(toPatch('reply_to', 'foo@example.com', true)).toEqual({ reply_to: 'foo@example.com' });
  });

  it('sends a blank sender field as null and never a blank name', () => {
    expect(toPatch('reply_to', ' ')).toEqual({ reply_to: null });
    expect(toPatch('from_name', '')).toEqual({ from_name: null });
    expect(toPatch('name', '  ')).toBeNull();
  });

  it('says why a value is not saved', () => {
    expect(fieldError('reply_to', 'user@', false)).toBe('newsletter.editor.meta.reply_to_invalid');
    expect(fieldError('reply_to', 'user@example.com', true)).toBeNull();
    expect(fieldError('name', '  ')).toBe('newsletter.editor.meta.name_required');
    expect(fieldError('subject', '')).toBeNull();
  });
});

describe('CampaignMeta isReplyTo', () => {
  it('wants a dot in the domain, as the server does', () => {
    expect(isReplyTo('a@b')).toBe(false);
    for (const bad of ['.a@b.io', 'a.@b.io', 'a..b@c.io', 'a@b.1', 'a@-b.io', 'a@b_c.io']) {
      expect(isReplyTo(bad)).toBe(false);
    }
    expect(isReplyTo('a@b.co.uk')).toBe(true);
    expect(isReplyTo('a@b.io')).toBe(true);
    expect(isReplyTo('')).toBe(true);
  });
});
