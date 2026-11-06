import { describe, expect, it } from 'vitest';

import { toPatch } from './CampaignMeta';

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
});
