import { keys } from '../utils/i18n';
import type { FormValue, FormValues } from '../utils/submission-values';
import type { DefinitionResult, SubmissionDefinition } from '../utils/submissions-form-api';

export type Phase = 'loading' | 'ready' | 'submitting' | 'success' | 'unavailable';
export type Problem = { key: string; params?: Record<string, unknown> };
/** A field key, `consent`, or the error summary / success message. */
export type FocusTarget = string;

export const CONSENT_KEY = 'consent';

export const form = keys.records.public_submissions.form;
export const errors = keys.records.public_submissions.errors;

/** The refusals with a message of their own; anything else is `generic`. */
export const BY_CODE: Record<string, string> = {
  form_expired: errors.form_expired,
  rate_limited: errors.rate_limited,
  captcha_failed: errors.captcha_failed,
  captcha_unavailable: errors.captcha_unavailable,
  bad_origin: errors.bad_origin,
  seats_busy: errors.seats_busy,
};

/** A registration the event no longer takes: the panel swaps to the matching state. */
export const GONE = new Set(['registration_full', 'registration_closed', 'event_unavailable']);

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

export type Options = {
  typeKey: string;
  locale: string | undefined;
  block?: string;
  /** Off in the editor with no type chosen: nothing is fetched. */
  enabled?: boolean;
  onFocus?: (target: FocusTarget) => void;
  /** Where the definition comes from, when it is not the plain form route (a registration
   *  asks its event and occurrence). Used for the first load and for a refetch. */
  load?: (signal?: AbortSignal) => Promise<DefinitionResult>;
  /** The server said the event no longer takes this registration (`registration_full`, ...). */
  onGone?: (code: string) => void;
};

/** The extra wait past the token's minimum age, for the clock and the trip. */
const MARGIN_MS = 300;

export function wait(seconds: number | undefined): Promise<void> {
  const ms = seconds ? seconds * 1000 + MARGIN_MS : 0;
  return ms > 0 ? new Promise((resolve) => setTimeout(resolve, ms)) : Promise.resolve();
}
