/**
 * How a raw error `field` is written on screen.
 *
 * The API reports a schema field by its bare key, and a record payload error
 * as `data.<key>` — `useRecordEditor` already strips that prefix before
 * focusing the input, but the two places that *print* the field showed the
 * prefix (R11): "data.title: Not a valid email address" in the editor's
 * unplaceable-errors list and in `InvalidNotice`. The prefix is the wire
 * shape of the envelope, not a name anybody typed.
 */
const DATA_PREFIX = 'data.';

export function displayFieldKey(field: string): string {
  return field.startsWith(DATA_PREFIX) ? field.slice(DATA_PREFIX.length) : field;
}
