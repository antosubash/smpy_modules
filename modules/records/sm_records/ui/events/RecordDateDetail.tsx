/** The calendar detail of a record's date: the default detail with one action, "Open record",
 *  to the record's own page (set by the server only for a viewer who may read the type). */
import type { DetailProps } from '@simple-module-py/events';
import { keys, useT } from '../utils/i18n';

export default function RecordDateDetail(props: DetailProps) {
  const { t } = useT();
  const { Default, occurrence } = props;
  const link = occurrence.url ? (
    <a href={occurrence.url} className="underline">
      {t(keys.records.events.detail.open_record)}
    </a>
  ) : null;
  return <Default {...props} actions={link} />;
}
