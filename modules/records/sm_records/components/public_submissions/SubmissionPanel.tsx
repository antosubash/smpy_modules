import type { RecordRead, TypeRead } from '../../utils/types';
import { SubmissionActions } from './SubmissionActions';
import { SubmissionDetails } from './SubmissionDetails';
import { SubscriberActions } from './SubscriberActions';

/**
 * What the record editor shows of a website submission (#101): the read-only
 * system fields, and — on a saved record — its actions: a contact form's
 * resend and spam, a newsletter subscriber's confirmation and unsubscribe.
 * One component so `RecordEditor` gains a line, not a block (300-line cap).
 */
export function SubmissionPanel({
  type,
  current,
  onChanged,
}: {
  type: TypeRead;
  current: RecordRead | null;
  onChanged: (record: RecordRead) => void;
}) {
  const kind = type.public_submissions?.kind;
  return (
    <>
      <SubmissionDetails fields={type.fields} data={current?.data} />
      {current && kind === 'form' && (
        <SubmissionActions type={type} record={current} onChanged={onChanged} />
      )}
      {current && kind === 'subscription' && (
        <SubscriberActions type={type} record={current} onChanged={onChanged} />
      )}
    </>
  );
}
