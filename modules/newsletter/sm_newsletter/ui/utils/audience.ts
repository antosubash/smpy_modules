/** A campaign's `audience` string (`all`, `tag:<choice>`, `segment:<id>`), as the picker edits it. */

export type AudienceChoice =
  | { kind: 'all' }
  | { kind: 'tag'; tag: string }
  | { kind: 'segment'; segmentId: number };

const TAG = 'tag:';
const SEGMENT = 'segment:';

export function parseAudience(raw: string): AudienceChoice {
  if (raw.startsWith(TAG) && raw.length > TAG.length) {
    return { kind: 'tag', tag: raw.slice(TAG.length) };
  }
  if (raw.startsWith(SEGMENT)) {
    const digits = raw.slice(SEGMENT.length);
    if (/^[0-9]+$/.test(digits)) return { kind: 'segment', segmentId: Number(digits) };
  }
  return { kind: 'all' };
}

export function formatAudience(choice: AudienceChoice): string {
  if (choice.kind === 'tag') return `${TAG}${choice.tag}`;
  if (choice.kind === 'segment') return `${SEGMENT}${choice.segmentId}`;
  return 'all';
}
