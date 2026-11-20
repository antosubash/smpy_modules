/** What the server says is wrong with a calendar's source settings: after a refused save, and for
 *  what is already stored. Grouped per source id and per dotted path under its settings. */
import { ApiError } from '../../utils/api';
import type { SourceEntryInput } from '../../utils/api-extensions';
import type { CalendarSource } from '../../utils/types';

export type Errors = Record<string, Record<string, string>>;
export type Problems = { errors: Errors; codes: Errors };

/** `sources.<i>.settings.<path>` messages and codes, grouped by the source sent at index `i`. */
export function groupErrors(error: unknown, sent: readonly SourceEntryInput[]): Problems {
  const out: Problems = { errors: {}, codes: {} };
  if (!(error instanceof ApiError) || error.status !== 422) return out;
  for (const [path, message] of Object.entries(error.messages)) {
    const [head, index, settings, ...rest] = path.split('.');
    const id = head === 'sources' && settings === 'settings' ? sent[Number(index)]?.id : undefined;
    if (!id) continue;
    const name = rest.join('.');
    out.errors[id] = { ...out.errors[id], [name]: message };
    const code = error.codes[path];
    if (code) out.codes[id] = { ...out.codes[id], [name]: code };
  }
  return out;
}

/** What the server says is wrong with the stored settings, as the same shape a failed save has. */
export function storedProblems(sources: readonly CalendarSource[]): Problems {
  const out: Problems = { errors: {}, codes: {} };
  for (const source of sources) {
    for (const problem of source.problems ?? []) {
      const name = problem.loc.join('.');
      out.errors[source.id] = { ...out.errors[source.id], [name]: problem.message };
      out.codes[source.id] = { ...out.codes[source.id], [name]: problem.code };
    }
  }
  return out;
}
