/** The field messages for `timeProblems`, shared by the Move and quick-create dialogs. */
import { keys } from '../../utils/i18n';
import type { timeProblems } from './quickCreate';

type Translate = (key: string) => string;
const errors = keys.events.errors;

export function timeErrors(
  problem: ReturnType<typeof timeProblems>,
  t: Translate,
): Record<string, string> {
  const text = (kind: 'skipped' | 'invalid' | 'order') =>
    t(
      kind === 'order'
        ? errors.end_before_start
        : kind === 'invalid'
          ? errors.invalid_datetime
          : errors.invalid_local_time,
    );
  return {
    ...(problem.start ? { 'times.start': text(problem.start) } : {}),
    ...(problem.end ? { 'times.end': text(problem.end) } : {}),
  };
}
