import type { ValidationError } from '../../utils/types';

/** First message for `field`, or `undefined`. Shared by the metadata form
 *  and the field rows so a 422's `errors[]` lands on the right input. */
export function fieldMessage(errors: ValidationError[], field: string): string | undefined {
  return errors.find((e) => e.field === field)?.message;
}
