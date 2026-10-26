/**
 * The `RecordForm` block's state machine (#101, design §8):
 * `loading → ready → submitting → success`, with `unavailable` for a form
 * that is not (or no longer) accepting submissions.
 *
 * - The definition is fetched live on mount, never read from page JSON.
 * - `form_expired` (a stale or too-young token) fetches a fresh definition
 *   and sends once more, by itself; a second refusal is shown.
 * - `form_changed` re-renders the form from the definition the 409 carries,
 *   keeps every value whose field still exists, and asks the visitor to check
 *   and send again.
 * - A 422 is mapped onto the fields it names; a 429 says how long to wait.
 *
 * Every message is a catalogue key, translated by the component.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { keys } from '../utils/i18n';
import {
  type FormValue,
  type FormValues,
  missingRequired,
  payloadFor,
  valuesFor,
} from '../utils/submission-values';
import {
  fetchDefinition,
  type SubmissionDefinition,
  type SubmitResult,
  submitForm,
} from '../utils/submissions-form-api';

export type Phase = 'loading' | 'ready' | 'submitting' | 'success' | 'unavailable';
export type Problem = { key: string; params?: Record<string, unknown> };
/** A field key, `consent`, or the error summary / success message. */
export type FocusTarget = string;

export const CONSENT_KEY = 'consent';

const form = keys.records.public_submissions.form;
const errors = keys.records.public_submissions.errors;

/** The refusals with a message of their own; anything else is `generic`. */
const BY_CODE: Record<string, string> = {
  form_expired: errors.form_expired,
  rate_limited: errors.rate_limited,
  captcha_failed: errors.captcha_failed,
  captcha_unavailable: errors.captcha_unavailable,
  bad_origin: errors.bad_origin,
};

export type SubmissionForm = {
  phase: Phase;
  definition: SubmissionDefinition | null;
  values: FormValues;
  setValue: (key: string, value: FormValue) => void;
  consent: boolean;
  setConsent: (value: boolean) => void;
  hp: string;
  setHp: (value: string) => void;
  setCaptcha: (response: string) => void;
  /** Bumped whenever the CAPTCHA widget must render afresh. */
  captchaRound: number;
  fieldErrors: Record<string, string>;
  problem: Problem | null;
  changed: boolean;
  submit: () => Promise<void>;
};

type Options = {
  typeKey: string;
  locale: string | undefined;
  block?: string;
  /** Off in the editor with no type chosen: nothing is fetched. */
  enabled?: boolean;
  onFocus?: (target: FocusTarget) => void;
};

/** The extra wait past the token's minimum age, for the clock and the trip. */
const MARGIN_MS = 300;

function wait(seconds: number | undefined): Promise<void> {
  const ms = seconds ? seconds * 1000 + MARGIN_MS : 0;
  return ms > 0 ? new Promise((resolve) => setTimeout(resolve, ms)) : Promise.resolve();
}

export function useSubmissionForm({
  typeKey,
  locale,
  block,
  enabled = true,
  onFocus,
}: Options): SubmissionForm {
  const [phase, setPhase] = useState<Phase>('loading');
  const [definition, setDefinition] = useState<SubmissionDefinition | null>(null);
  const [values, setValues] = useState<FormValues>({});
  const [consent, setConsent] = useState(false);
  const [hp, setHp] = useState('');
  const [captchaRound, setCaptchaRound] = useState(0);
  const captcha = useRef('');
  const inFlight = useRef(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<Problem | null>(null);
  const [changed, setChanged] = useState(false);
  const focus = useRef(onFocus);
  focus.current = onFocus;

  const resetCaptcha = useCallback(() => {
    captcha.current = '';
    setCaptchaRound((round) => round + 1);
  }, []);

  /** Render `next`. `keepCaptcha` when the server refused before it checked
   *  the CAPTCHA (`form_expired`, `form_changed`), so the response is still unused. */
  const adopt = useCallback(
    (next: SubmissionDefinition, previous: FormValues = {}, keepCaptcha = false) => {
      setDefinition(next);
      setValues(valuesFor(next, previous));
      if (!keepCaptcha || !next.captcha) resetCaptcha();
    },
    [resetCaptcha],
  );

  useEffect(() => {
    if (!enabled || !typeKey) return;
    const controller = new AbortController();
    setPhase('loading');
    fetchDefinition(typeKey, locale, controller.signal)
      .then((result) => {
        if (result.status === 'ready') {
          adopt(result.definition);
          setPhase('ready');
        } else {
          setPhase('unavailable');
          if (result.status === 'error') setProblem({ key: errors.network });
        }
      })
      .catch(() => undefined); // aborted on unmount or a new type key
    return () => controller.abort();
  }, [typeKey, locale, enabled, adopt]);

  const setValue = useCallback((key: string, value: FormValue) => {
    setValues((prev) => ({ ...prev, [key]: value }));
    setFieldErrors((prev) => {
      if (!(key in prev)) return prev;
      const { [key]: _gone, ...rest } = prev;
      return rest;
    });
  }, []);

  const refuse = (next: Problem, target: FocusTarget = 'summary') => {
    setProblem(next);
    setPhase('ready');
    focus.current?.(target);
  };

  const refused = async (
    result: Exclude<SubmitResult, { ok: true }>,
    current: SubmissionDefinition,
    retried: boolean,
  ): Promise<void> => {
    if (result.status === 404) {
      setPhase('unavailable');
      return;
    }
    if (result.code === 'form_expired' && !retried) {
      const fresh = await fetchDefinition(typeKey, locale);
      if (fresh.status === 'ready') {
        adopt(fresh.definition, values, true);
        // The fresh token is refused until it is `min_fill_seconds` old.
        await wait(fresh.definition.min_fill_seconds);
        return send(fresh.definition, true);
      }
    }
    if (result.code === 'form_changed') {
      adopt(result.definition ?? current, values, true);
      setChanged(true);
      return refuse({ key: form.changed });
    }
    if (result.status === 422) {
      const mapped: Record<string, string> = {};
      for (const item of result.errors) {
        mapped[item.field] =
          item.field === CONSENT_KEY ? form.consent_required : form.field_invalid;
      }
      setFieldErrors(mapped);
      const first = current.fields.find((field) => field.key in mapped)?.key;
      return refuse(
        { key: form.invalid },
        first ?? (CONSENT_KEY in mapped ? CONSENT_KEY : 'summary'),
      );
    }
    if (result.code === 'captcha_failed') {
      // Loaded before the host turned a CAPTCHA on: the form has no widget
      // to complete, so fetch the definition that names one.
      if (!current.captcha) {
        const fresh = await fetchDefinition(typeKey, locale);
        if (fresh.status === 'ready') adopt(fresh.definition, values);
      }
    }
    const key = (result.code && BY_CODE[result.code]) || errors.generic;
    refuse({ key, params: { seconds: result.retryAfter ?? 60 } });
  };

  const send = async (current: SubmissionDefinition, retried: boolean): Promise<void> => {
    setPhase('submitting');
    let result: SubmitResult;
    try {
      result = await submitForm(typeKey, {
        data: payloadFor(current.fields, values),
        token: current.token,
        hp,
        consent,
        ...(block ? { block } : {}),
        ...(locale ? { locale } : {}),
        ...(current.captcha ? { captcha_response: captcha.current } : {}),
      });
    } catch {
      // It may have reached the provider: a response is good for one check.
      if (current.captcha) resetCaptcha();
      return refuse({ key: errors.network });
    }
    if (result.ok) {
      setPhase('success');
      focus.current?.('success');
      return;
    }
    // Any refusal after the token check may have spent the response (a 422
    // comes after verification), so the widget starts over -- except
    // `form_expired` and `form_changed`, refused before it: the response is
    // still unused and the resend reuses it.
    const beforeCheck = result.code === 'form_expired' || result.code === 'form_changed';
    if (current.captcha && !beforeCheck) resetCaptcha();
    return refused(result, current, retried);
  };

  const submit = async (): Promise<void> => {
    if (!definition || phase === 'submitting') return;
    const missing: Record<string, string> = {};
    for (const key of missingRequired(definition.fields, values)) missing[key] = form.required;
    if (definition.consent?.required && !consent) missing[CONSENT_KEY] = form.consent_required;
    setChanged(false);
    if (Object.keys(missing).length > 0) {
      setFieldErrors(missing);
      const first = definition.fields.find((field) => field.key in missing)?.key ?? CONSENT_KEY;
      return refuse({ key: form.invalid }, first);
    }
    setFieldErrors({});
    // A CAPTCHA not yet completed would only come back `captcha_failed`.
    if (definition.captcha && !captcha.current) return refuse({ key: errors.captcha_failed });
    setProblem(null);
    // `phase` is state, so clicks inside one tick all still see `ready`:
    // the ref is what makes a burst of clicks one submission.
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      await send(definition, false);
    } finally {
      inFlight.current = false;
    }
  };

  return {
    phase,
    definition,
    values,
    setValue,
    consent,
    setConsent: (value: boolean) => {
      setConsent(value);
      if (value) setFieldErrors(({ [CONSENT_KEY]: _gone, ...rest }) => rest);
    },
    hp,
    setHp,
    setCaptcha: (response: string) => {
      captcha.current = response;
    },
    captchaRound,
    fieldErrors,
    problem,
    changed,
    submit,
  };
}
