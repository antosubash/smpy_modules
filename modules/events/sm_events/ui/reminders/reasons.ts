import { keys } from '../utils/i18n';

const delivery = keys.events.reminders.delivery;

/** Why reminders cannot be delivered, by the server's code (`AVAILABILITY_REASONS`); the control
 *  and the Delivery card say the same words. `tests/reminders/test_labels.py` ties both tables
 *  to the codes and the catalogue. */
export const AVAILABILITY_REASONS: Record<string, string> = {
  disabled: delivery.reason_disabled,
  no_public_base_url: delivery.reason_no_public_base_url,
  no_mail_transport: delivery.reason_no_mail_transport,
  console_mail: delivery.reason_console_mail,
};

/** The failure codes the ledger counts (`REMINDER_SEND_FAILED`, `REMINDER_CODE_SEND_TIMEOUT`, `REMINDER_CODE_TOO_LATE`). */
export const FAILED_CODES: Record<string, string> = {
  send_failed: delivery.failed_code_send_failed,
  send_timeout: delivery.failed_code_send_timeout,
  too_late: delivery.failed_code_too_late,
};
