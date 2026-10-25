import type { RecordRead, TypeRead } from '../../utils/types';
import { SubmissionActions } from './SubmissionActions';
import { SubmissionDetails } from './SubmissionDetails';

/**
 * What the record editor shows of a website submission (#101): the read-only
 * system fields, and — on a contact form's saved record — its actions. One
 * component so `RecordEditor` gains a line, not a block (300-line cap).
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
  const isForm = type.public_submissions?.kind === 'form';
  return (
    <>
      <SubmissionDetails fields={type.fields} data={current?.data} />
      {current && isForm && (
        <SubmissionActions type={type} record={current} onChanged={onChanged} />
      )}
    </>
  );
}
