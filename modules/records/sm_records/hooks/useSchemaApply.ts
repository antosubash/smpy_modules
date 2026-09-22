/**
 * Generic 409-handling for a schema-changing write. `PUT /types/{key}` and
 * `POST /types/{key}/revisions/{version}/restore` return the same shapes
 * (design's contract): a stale `expected_version` (`current`), a restrictive
 * change's dry-run (`report`), or a re-added key's orphaned values
 * (`conflicts`) — each retried by merging `force`/`orphaned` onto the same
 * body. One hook covers both call sites (`TypeEditor`'s save and
 * `TypeRevisions`' restore) instead of duplicating the branching twice.
 *
 * A caller supplies the actual `attempt` function per call — `run` and
 * `retryWith` don't know which endpoint they're hitting, only the shared
 * error shape coming back from it.
 */

import { useCallback, useRef, useState } from 'react';

import { ApiError } from '../utils/api';
import type { DryRunReport, TypeRead, ValidationError } from '../utils/types';

export type SchemaApplyBody = {
  expected_version: number;
  force?: boolean;
  orphaned?: 'restore' | 'discard';
  [key: string]: unknown;
};

export type SchemaApplyState = {
  pending: boolean;
  errors: ValidationError[];
  versionConflict: TypeRead | null;
  report: DryRunReport | null;
  conflicts: Record<string, number> | null;
};

const IDLE: SchemaApplyState = {
  pending: false,
  errors: [],
  versionConflict: null,
  report: null,
  conflicts: null,
};

export function useSchemaApply(onApplied: (result: TypeRead) => void) {
  const [state, setState] = useState<SchemaApplyState>(IDLE);
  const attemptRef = useRef<((body: SchemaApplyBody) => Promise<TypeRead>) | null>(null);
  const bodyRef = useRef<SchemaApplyBody | null>(null);

  const reset = useCallback(() => setState(IDLE), []);

  /** Send `body` through `attempt`, remembering both so `retryWith` can
   *  re-send with a patch merged on top. Rethrows anything that isn't one of
   *  the four known shapes, for the caller to toast. */
  const run = useCallback(
    async (attempt: (body: SchemaApplyBody) => Promise<TypeRead>, body: SchemaApplyBody) => {
      attemptRef.current = attempt;
      bodyRef.current = body;
      setState({ ...IDLE, pending: true });
      try {
        const result = await attempt(body);
        setState(IDLE);
        onApplied(result);
        return result;
      } catch (err) {
        if (err instanceof ApiError && err.status === 409 && err.body?.report) {
          // `report` is a union since the bulk routes started using the same
          // key; a schema refusal is the one with `checked` on it, and no
          // other 409 this hook sees carries a report at all.
          const report = err.body.report;
          setState({ ...IDLE, report: 'checked' in report ? report : null });
        } else if (err instanceof ApiError && err.status === 409 && err.body?.conflicts) {
          setState({ ...IDLE, conflicts: err.body.conflicts });
        } else if (err instanceof ApiError && err.status === 409 && err.body?.current) {
          setState({ ...IDLE, versionConflict: err.body.current as TypeRead });
        } else if (err instanceof ApiError && err.status === 422 && err.body?.errors) {
          setState({ ...IDLE, errors: err.body.errors });
        } else {
          setState(IDLE);
          throw err;
        }
        return null;
      }
    },
    [onApplied],
  );

  const retryWith = useCallback(
    (patch: Partial<SchemaApplyBody>) => {
      if (!attemptRef.current || !bodyRef.current) return Promise.resolve(null);
      return run(attemptRef.current, { ...bodyRef.current, ...patch });
    },
    [run],
  );

  return { ...state, run, retryWith, reset };
}
