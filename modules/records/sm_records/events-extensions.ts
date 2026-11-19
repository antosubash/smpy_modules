/** Records' contribution to the events calendar: the settings form and the detail of the
 *  `records:dates` source. Only this package's entry point is imported here (never a deep path),
 *  and both components are lazy, so none of their code is loaded unless an events screen needs it. */
import { registerSource } from '@simple-module-py/events';

registerSource({
  id: 'records:dates',
  SettingsSection: () => import('./ui/events/RecordDatesSettings'),
  Detail: () => import('./ui/events/RecordDateDetail'),
});
