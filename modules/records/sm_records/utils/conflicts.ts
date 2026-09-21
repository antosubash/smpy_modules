/**
 * Reading a 409 that is *not* about a stale version (UX review R8b).
 *
 * `services/errors.py::Conflict` carries `current` only for an
 * optimistic-concurrency refusal; the two collision refusals — a duplicate
 * `unique` value (`_claims.py::ensure_unique`) and a taken slug
 * (`_claims.py::_slug_taken`) — arrive as a bare `detail` sentence. The
 * editor used to render both as a toast reading like a sentence from a
 * database, with nothing marking the input that caused it.
 *
 * Parsing English prose from the server is not lovely, and the alternative —
 * a machine-readable `field` on the 409 body — is the right long-term answer
 * (it would be a server change, out of this pass's scope). Both sentences are
 * produced by one `f"..."` each, so the two patterns below are exact rather
 * than heuristic, and a miss degrades to exactly today's behaviour: a toast
 * and no inline mark.
 */

/** `'{key}' must be unique; {value!r} is already taken`. */
const UNIQUE_RE = /^'([a-z][a-z0-9_]*)' must be unique/;

/** `slug {slug!r} is already used by another {type} record in {locale!r}`. */
const SLUG_RE = /^slug '.*' is already used by another /;

/** The envelope input a slug collision belongs to — `RecordEnvelopeFields`
 *  keys its own messages by this name, the same way a 422 does. */
const SLUG_FIELD = 'slug';

/**
 * Which input a collision 409 is about, or `null` when the detail is one of
 * the other conflicts (a reindex in progress, a translation-group clash) that
 * no single input can own.
 *
 * `fieldKeys` is the type's own field list: a `unique` complaint naming a key
 * this type does not have is not attributed, so a future server message that
 * happens to start with a quoted word cannot light up an unrelated input.
 */
export function conflictField(detail: string, fieldKeys: Iterable<string>): string | null {
  const trimmed = detail.trim();
  if (SLUG_RE.test(trimmed)) return SLUG_FIELD;
  const unique = UNIQUE_RE.exec(trimmed);
  if (!unique) return null;
  const key = unique[1];
  for (const candidate of fieldKeys) {
    if (candidate === key) return key;
  }
  return null;
}
