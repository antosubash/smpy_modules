/** The registration forms an event can point at: `GET` lists the ones the caller may view and
 *  says whether they may create one, `POST` creates one with the defaults an event needs. */
import { request } from './api';

export type RegistrationForm = {
  key: string;
  label: string;
  /** `false`: the form is switched off, so nobody can register through it. */
  enabled: boolean;
  /** `false`: seats are taken at submit without confirming an address. */
  double_opt_in: boolean;
  attendees_url: string;
};
export type RegistrationFormList = { items: RegistrationForm[]; can_create: boolean };

export const listRegistrationForms = (): Promise<RegistrationFormList> =>
  request('/registration-forms');
export const createRegistrationForm = (): Promise<{ key: string }> =>
  request('/registration-forms', { method: 'POST' });
