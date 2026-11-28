// @vitest-environment happy-dom
import { updateI18n } from '@simple-module-py/i18n';
import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import {
  definition,
  field,
  server,
} from '../components/public_submissions/form/record-form-test-support';
import { mount, settle } from '../page-tests/test-dom';
import { loadCatalogue } from '../utils/PageLocale';

vi.mock('../components/public_submissions/form/CaptchaWidget', () => ({
  CaptchaWidget: () => null,
}));
const { default: RegistrationPanel } = await import('./RegistrationPanel');

const EID = '3f1c2a52-0000-4000-8000-000000000001';
const baseProps = { typeKey: 'regs', eventId: EID, occurrenceKey: EID };
const open = {
  availability: {
    state: 'open',
    seats_left: null,
    few_left: false,
    opens_at: null,
    closes_at: null,
  },
  event: {
    title: 'Open day',
    when_text: 'Wed 1 Jul, 10:00',
    venue_name: 'Hall',
    address: null,
  },
  definition: {
    ...definition({ kind: 'registration' as never, double_opt_in: true } as never),
    fields: [
      field('sm_name', 'text', { required: true }),
      field('sm_email', 'email', { required: true }),
    ],
    consent: null,
  },
};
const text = () => document.body.textContent ?? '';

beforeAll(() => loadCatalogue('de'));
afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
  document.documentElement.lang = '';
  updateI18n({ locale: 'en', messages: {} });
});

it('speaks the page language rather than the visitor console language (#488)', async () => {
  // Console is German, page is English -> English form strings.
  updateI18n({
    locale: 'de',
    messages: {
      'records.public_submissions.registration.panel.for_event': 'Anmeldung für {title}',
      'records.public_submissions.registration.panel.submit': 'Anmelden',
      'records.public_submissions.form.honeypot': 'Dieses Feld leer lassen',
    },
  });
  const enCalls = server({ status: 200, body: open });
  const enView = await mount(<RegistrationPanel {...baseProps} locale="en" />);
  await settle();
  expect(enCalls[0]?.url).toBe(
    `/api/records/submissions/regs/registration?event=${EID}&occurrence=${EID}&locale=en`,
  );
  expect(text()).toContain('Registering for Open day');
  expect(text()).toContain('Leave this field empty');
  expect(enView.find('button[type="submit"]')?.textContent).toBe('Register');
  await enView.unmount();

  // Console is English, page is German -> German form strings.
  updateI18n({ locale: 'en', messages: {} });
  const deCalls = server({ status: 200, body: open });
  const deView = await mount(<RegistrationPanel {...baseProps} locale="de" />);
  await settle();
  expect(deCalls[0]?.url).toBe(
    `/api/records/submissions/regs/registration?event=${EID}&occurrence=${EID}&locale=de`,
  );
  expect(text()).toContain('Anmeldung für Open day');
  expect(text()).toContain('Dieses Feld leer lassen');
  expect(deView.find('button[type="submit"]')?.textContent).toBe('Anmelden');
  await deView.unmount();
});
