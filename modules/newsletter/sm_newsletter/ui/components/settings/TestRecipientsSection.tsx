import { Textarea } from '@simple-module-py/ui/components/ui/textarea';
import { useState } from 'react';

import { parseAddresses } from '../../utils/addresses';
import { keys, useT } from '../../utils/i18n';
import { Field, Section } from './FormParts';

/** The server's bound (`MAX_EXTRA_TEST_RECIPIENTS` in `web/schemas/settings.py`). */
export const MAX_EXTRA_TEST_RECIPIENTS = 20;

/** `test_send_extra_recipients` (#348): the addresses a test may go to besides
 *  the sender's own and the organisation's members'. The text is kept as typed
 *  so a new line can be started; the parsed list is what the form saves. */
export function TestRecipientsSection({
  value,
  disabled,
  onChange,
}: {
  value: string[];
  disabled: boolean;
  onChange: (next: string[]) => void;
}) {
  const { t } = useT();
  const copy = keys.newsletter.settings.test_sends;
  const [text, setText] = useState(value.join('\n'));
  const id = 'newsletter-settings-test-recipients';
  const tooMany = parseAddresses(text).length > MAX_EXTRA_TEST_RECIPIENTS;
  return (
    <Section title={t(copy.title)}>
      <Field id={id} label={t(copy.extra_recipients)} hint={t(copy.extra_recipients_hint)}>
        <Textarea
          id={id}
          rows={3}
          value={text}
          disabled={disabled}
          aria-invalid={tooMany}
          onChange={(e) => {
            setText(e.target.value);
            onChange(parseAddresses(e.target.value));
          }}
        />
        {tooMany && (
          <p className="text-sm text-destructive">
            {t(copy.too_many, { max: MAX_EXTRA_TEST_RECIPIENTS })}
          </p>
        )}
      </Field>
    </Section>
  );
}
