/** A failed probe's message in the console's language, chosen by its `code` (#347).
 *
 * The API sends a stable code and a fixed English message, never the provider's
 * own text. A result with no known code (a network error before any answer)
 * shows the message it carries. */

import type { ModelsResult, TestResult } from './api';
import { keys, type Translate } from './i18n';

const p = keys.ai.probe;

const MESSAGES: Record<string, string> = {
  base_url_refused: p.base_url_refused,
  not_configured: p.not_configured,
  key_unreadable: p.key_unreadable,
  unreachable: p.unreachable,
  connection_refused: p.connection_refused,
  timeout: p.timeout,
  unauthorised: p.unauthorised,
  http_error: p.http_error,
  other: p.other,
};

export function probeMessage(
  t: Translate,
  result: Pick<TestResult | ModelsResult, 'code' | 'error' | 'status'>,
): string {
  const code = result.code ?? '';
  if (!Object.hasOwn(MESSAGES, code)) return result.error;
  return t(MESSAGES[code], { status: result.status ?? 0 });
}
