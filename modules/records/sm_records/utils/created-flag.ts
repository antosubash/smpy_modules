/**
 * Where a create leaves word that it happened, for the editor it navigates
 * to (R22a). Split out of `useRecordEditor` for the 300-line cap — it is the
 * same read-once-and-clear `sessionStorage` shape `utils/duplicate.ts` uses
 * for "Save as copy", just narrower (one uuid, not a payload).
 *
 * `sessionStorage` and not a query parameter or component state: the create
 * *navigates*, so nothing a hook holds survives it — and a `?created=1`
 * would sit in the address bar of a URL people copy and share, claiming the
 * record was created again every time it is opened. Read once and cleared,
 * so a reload doesn't repeat the toast either.
 */

const CREATED_FLAG = 'sm-records-created-uuid';

/** Remember it now; the page this navigates to is the one that will say so.
 *  A browser with storage blocked simply doesn't get the toast. */
export function rememberCreated(uuid: string): void {
  try {
    window.sessionStorage.setItem(CREATED_FLAG, uuid);
  } catch {
    // Private mode, blocked site data — nothing to recover, and a missing
    // confirmation must never fail a save that already succeeded.
  }
}

/** …and take it, if it is this record's. */
export function takeCreated(uuid: string | undefined): boolean {
  if (typeof window === 'undefined' || uuid === undefined) return false;
  try {
    if (window.sessionStorage.getItem(CREATED_FLAG) !== uuid) return false;
    window.sessionStorage.removeItem(CREATED_FLAG);
    return true;
  } catch {
    return false;
  }
}
