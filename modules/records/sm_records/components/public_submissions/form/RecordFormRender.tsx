/**
 * `RecordForm` render (#101, design §8): a website form for a record type
 * that accepts submissions — a contact form or a newsletter signup.
 *
 * The block's props only name the type and add wording; everything the
 * server relies on — which fields, their validation, the consent text, the
 * CAPTCHA — comes from the definition fetched live on mount
 * (`useSubmissionForm`). One render path for the Puck editor and the public
 * page; in the editor the form shows the live definition with its submit
 * disabled.
 *
 * Accessibility: a labelled form, the problem summary in a `role="alert"`
 * region that takes focus, per-field errors tied to their inputs, focus on
 * the first field in error, and the thank-you message focused once sent.
 * The honeypot is off-screen, out of the tab order and hidden from assistive
 * technology.
 */

import { Section } from '@simple-module-py/pagebuilder/pagebuilder/components/widgets/_shared';
import { type CSSProperties, type ReactNode, useCallback, useId, useState } from 'react';
import { type FocusTarget, useSubmissionForm } from '../../../hooks/useSubmissionForm';
import { keys, useT } from '../../../utils/i18n';
import { FormBody } from './RecordFormFields';
import { HELP_STYLE, LABEL_STYLE } from './SubmissionInput';
import type { RecordFormProps } from './types';

export type RecordFormRenderProps = RecordFormProps & {
  id?: string;
  puck?: { isEditing?: boolean };
};

const HEADING_STYLE: CSSProperties = {
  color: 'var(--pb-heading-color)',
  fontFamily: 'var(--pb-display-font)',
  fontWeight: 'var(--pb-display-weight)' as CSSProperties['fontWeight'],
};
const BODY_STYLE: CSSProperties = { color: 'var(--pb-body-color)' };

const ps = keys.records.public_submissions;

/** The page's language: pagebuilder writes it on `<html lang>`. */
function pageLang(): string | undefined {
  if (typeof document === 'undefined') return undefined;
  return document.documentElement.lang || undefined;
}

export function RecordFormRender(props: RecordFormRenderProps) {
  const { t } = useT();
  const editing = Boolean(props.puck?.isEditing);
  const base = useId();
  const [locale] = useState(pageLang);
  const summaryId = `${base}-summary`;
  const successId = `${base}-success`;
  const fieldId = (key: string) => `${base}-${key}`;

  const onFocus = useCallback(
    (target: FocusTarget) => {
      const id =
        target === 'summary' ? summaryId : target === 'success' ? successId : `${base}-${target}`;
      window.setTimeout(() => document.getElementById(id)?.focus(), 0);
    },
    [base, summaryId, successId],
  );

  const form = useSubmissionForm({
    typeKey: props.typeKey,
    locale,
    block: props.id?.slice(0, 100),
    enabled: Boolean(props.typeKey),
    onFocus,
  });
  const overrides = new Map((props.labels ?? []).map((entry) => [entry.field, entry]));
  const subscription = form.definition?.kind === 'subscription';

  const header = (props.title || props.intro) && (
    <div className="mb-6">
      {props.title && (
        <h2 className="text-2xl font-semibold sm:text-3xl" style={HEADING_STYLE}>
          {props.title}
        </h2>
      )}
      {props.intro && (
        <p className="mt-2" style={BODY_STYLE}>
          {props.intro}
        </p>
      )}
    </div>
  );

  let body: ReactNode;
  if (!props.typeKey) {
    body = (
      <p className="text-sm" style={HELP_STYLE} data-testid="records-form-placeholder">
        {t(ps.block.placeholder)}
      </p>
    );
  } else if (form.phase === 'loading') {
    body = (
      <p className="text-sm" style={HELP_STYLE} aria-busy="true">
        {t(ps.form.loading)}
      </p>
    );
  } else if (form.phase === 'unavailable') {
    body = (
      <p className="text-sm" style={HELP_STYLE} data-testid="records-form-unavailable">
        {form.problem ? t(form.problem.key) : t(ps.form.unavailable)}
      </p>
    );
  } else if (form.phase === 'success') {
    body = (
      <div role="status" className="rounded-md border px-6 py-8" data-testid="records-form-success">
        <h3 id={successId} tabIndex={-1} className="text-xl font-medium" style={LABEL_STYLE}>
          {props.successTitle || t(ps.form.success_title)}
        </h3>
        <p className="mt-2" style={BODY_STYLE}>
          {props.successBody ||
            t(subscription ? ps.form.success_body_subscription : ps.form.success_body)}
        </p>
      </div>
    );
  } else {
    body = (
      <FormBody
        {...{ props, form, editing, fieldId, summaryId, overrides, subscription, locale }}
      />
    );
  }

  return (
    <Section variant="default" spacing="default">
      <div className="mx-auto max-w-2xl" data-testid="records-form">
        {header}
        {body}
      </div>
    </Section>
  );
}
