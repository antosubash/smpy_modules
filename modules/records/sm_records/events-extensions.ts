/** Records' contribution to the events module: the settings form and the detail of the
 *  `records:dates` source, and the registration provider (the form picker in the event editor and
 *  the panel on the public event page). Only this package's entry point is imported here (never a
 *  deep path), and every component is lazy, so none of their code is loaded unless an events
 *  screen needs it. */
import { registerRegistration, registerSource } from '@simple-module-py/events';

registerSource({
  id: 'records:dates',
  SettingsSection: () => import('./ui/events/RecordDatesSettings'),
  Detail: () => import('./ui/events/RecordDateDetail'),
});

registerRegistration({
  id: 'records:registration',
  EditorSection: () => import('./ui/events/RegistrationEditor'),
  PublicPanel: () => import('./ui/events/RegistrationPanel'),
});
