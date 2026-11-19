/** Records' registration panel on a public event page: the event's facts, what the occurrence
 *  offers now (states, never who is registered), and the form while it is open.
 *
 *  Everything comes live from the provider route (`fetchRegistration`), never from the page's
 *  cached props. The event and the occurrence travel only in that query: the form's signed token
 *  carries them back, so the submit has no event field. The panel never says whether an address was
 *  already registered: a submit answers one neutral thank-you, and what happened is told by mail.
 *  A refusal because the event filled up or closed meanwhile swaps the panel to that state. */
import type { RegistrationPanelProps } from '@simple-module-py/events';
import { useCallback, useId, useState } from 'react';
import { FormBody } from '../components/public_submissions/form/RecordFormFields';
import { type FocusTarget, useSubmissionForm } from '../hooks/useSubmissionForm';
import { keys, useT } from '../utils/i18n';
import { fetchRegistration, type RegistrationView } from '../utils/registration-api';

const copy = keys.records.public_submissions.registration.panel;
const BLANK = {
  typeKey: '',
  title: '',
  intro: '',
  submitLabel: '',
  successTitle: '',
  successBody: '',
  labels: [],
  kindHint: '',
};
const GONE_TEXT = {
  registration_full: copy.state_full,
  registration_closed: copy.state_closed,
  event_unavailable: copy.state_unavailable,
} as const;
const STATE_TEXT = {
  full: copy.state_full,
  closed: copy.state_closed,
  cancelled: copy.state_cancelled,
} as const;

function when(iso: string | null, locale: string): string {
  if (!iso) return '';
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? ''
    : new Intl.DateTimeFormat(locale, { dateStyle: 'long', timeStyle: 'short' }).format(date);
}

export default function RegistrationPanel({
  typeKey,
  eventId,
  occurrenceKey,
  locale,
}: RegistrationPanelProps) {
  const { t } = useT();
  const base = useId();
  const [view, setView] = useState<RegistrationView | null>(null);
  const [gone, setGone] = useState<keyof typeof GONE_TEXT | null>(null);
  const load = useCallback(
    async (signal?: AbortSignal) => {
      const result = await fetchRegistration(typeKey, eventId, occurrenceKey, locale, signal);
      if (result.status !== 'ready') return result;
      setView(result.view);
      return result.view.definition
        ? { status: 'ready' as const, definition: result.view.definition }
        : { status: 'unavailable' as const };
    },
    [typeKey, eventId, occurrenceKey, locale],
  );
  const onFocus = useCallback(
    (target: FocusTarget) => {
      const id =
        target === 'summary'
          ? `${base}-summary`
          : target === 'success'
            ? `${base}-success`
            : `${base}-${target}`;
      window.setTimeout(() => document.getElementById(id)?.focus(), 0);
    },
    [base],
  );
  const form = useSubmissionForm({
    typeKey,
    locale,
    load,
    onGone: (code) => setGone(code as keyof typeof GONE_TEXT),
    onFocus,
  });
  const info = view?.event;
  const state = view?.availability;
  const header = info ? (
    <header className="space-y-1">
      <h2 className="text-lg font-semibold">{t(copy.for_event, { title: info.title })}</h2>
      <p className="text-sm">
        {info.when_text}
        {info.venue_name ? ` · ${info.venue_name}` : ''}
      </p>
    </header>
  ) : null;

  let body = null;
  if (form.phase === 'loading') {
    body = (
      <p role="status" aria-busy="true" className="text-sm">
        {t(copy.loading)}
      </p>
    );
  } else if (gone) {
    body = <p role="status">{t(GONE_TEXT[gone])}</p>;
  } else if (form.phase === 'success') {
    body = (
      <div role="status" className="rounded-md border px-6 py-8" data-testid="registration-success">
        <h3 id={`${base}-success`} tabIndex={-1} className="text-xl font-medium">
          {t(copy.success_title)}
        </h3>
        <p className="mt-2">
          {t(
            form.definition?.double_opt_in === false
              ? copy.success_registered
              : copy.success_pending,
          )}
        </p>
      </div>
    );
  } else if (form.phase === 'unavailable') {
    if (form.problem) {
      body = (
        <p role="alert" className="text-sm">
          {t(form.problem.key)}
        </p>
      );
    } else if (state?.state === 'not_open_yet') {
      body = <p role="status">{t(copy.state_not_open, { time: when(state.opens_at, locale) })}</p>;
    } else if (state && state.state !== 'open') {
      body = <p role="status">{t(STATE_TEXT[state.state as keyof typeof STATE_TEXT])}</p>;
    } else {
      return null; // nothing to offer (a 404): the page around the panel is unaffected
    }
  } else {
    const left = state?.seats_left;
    body = (
      <>
        {state?.few_left ? <p className="text-sm font-medium">{t(copy.few_left)}</p> : null}
        {typeof left === 'number' ? (
          <p className="text-sm font-medium">
            {t(left === 1 ? copy.seats_left_one : copy.seats_left, { count: left })}
          </p>
        ) : null}
        <FormBody
          {...{
            props: { ...BLANK, submitLabel: t(copy.submit) },
            form,
            editing: false,
            fieldId: (key: string) => `${base}-${key}`,
            summaryId: `${base}-summary`,
            overrides: new Map(),
            subscription: false,
            locale,
          }}
        />
      </>
    );
  }
  return (
    <section aria-label={t(copy.heading)} className="space-y-4" data-testid="registration-panel">
      {header}
      {body}
    </section>
  );
}
