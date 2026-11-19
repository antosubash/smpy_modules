/** The registration section's form state, and its conversion to and from the API's bodies. */
import type { EventDetail, RegistrationIn, RegistrationMode } from './types-events';

const text = (value: string): string | null => (value.trim() === '' ? null : value);
const number = (value: string): number | null => (value.trim() === '' ? null : Number(value));

/** The registration section as typed: text for every number and time, like the rest of the form. */
export type RegistrationForm = {
  mode: RegistrationMode;
  url: string;
  provider: string;
  target: string;
  capacity: string;
  opens: string;
  closes: string;
  show_seats: boolean;
  reminder: string;
  /** Read-only facts from the server, never sent: the form is withheld from this editor, and
   *  whether this host still has the provider. */
  hidden: boolean;
  installed: boolean;
};
export const blankRegistration = (): RegistrationForm => ({
  mode: 'none',
  url: '',
  provider: '',
  target: '',
  capacity: '',
  opens: '',
  closes: '',
  show_seats: false,
  reminder: '',
  hidden: false,
  installed: true,
});
export function fromRegistration(event: EventDetail): RegistrationForm {
  const r = event.registration;
  if (!r)
    return {
      ...blankRegistration(),
      mode: event.registration_url ? 'external' : 'none',
      url: event.registration_url ?? '',
    };
  return {
    mode: r.mode,
    url: r.url ?? '',
    provider: r.provider ?? '',
    target: r.target ?? '',
    capacity: r.capacity === null ? '' : String(r.capacity),
    opens: r.opens_at_local ?? '',
    closes: r.closes_at_local ?? '',
    show_seats: r.show_seats,
    reminder: r.reminder_minutes === null ? '' : String(r.reminder_minutes),
    hidden: r.target_hidden,
    installed: r.provider_installed !== false,
  };
}

/** The API's body for the section: `undefined` when there is nothing to say (none, or a form the
 *  editor cannot read, whose stored settings must stay as they are). */
export function toRegistration(form: RegistrationForm): RegistrationIn | undefined {
  if (form.hidden || form.mode === 'none') return undefined;
  if (form.mode === 'external') return { mode: 'external', url: text(form.url) };
  return {
    mode: 'builtin',
    url: null,
    provider: text(form.provider),
    target: text(form.target),
    capacity: number(form.capacity),
    opens_at_local: text(form.opens),
    closes_at_local: text(form.closes),
    show_seats: form.show_seats,
    reminder_minutes: number(form.reminder),
  };
}
