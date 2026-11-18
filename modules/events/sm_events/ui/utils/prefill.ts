/** What the calendar's "More options" hands the new-event editor (`prefill` in the page
 *  props, validated by the server: anything it could not vouch for is absent). */
import type { FormState } from './event-form';

export type Prefill = {
  all_day: boolean | null;
  /** `YYYY-MM-DDTHH:MM`, or `YYYY-MM-DD` all day (the end then inclusive), in the calendar's zone. */
  start: string | null;
  end: string | null;
  title: string | null;
};

/** The empty form with the prefilled times and title laid on it. */
export function withPrefill(
  form: FormState,
  prefill: Prefill | null | undefined,
  defaultLocale: string,
): FormState {
  if (!prefill) return form;
  let next = form;
  if (prefill.start && prefill.end && prefill.all_day !== null) {
    next = { ...next, all_day: prefill.all_day, start: prefill.start, end: prefill.end };
  }
  const text = next.texts[defaultLocale];
  if (prefill.title && text) {
    next = {
      ...next,
      texts: { ...next.texts, [defaultLocale]: { ...text, title: prefill.title } },
    };
  }
  return next;
}
