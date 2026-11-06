/** Email, name, status, tags, the tenant-wide "won't receive" badge and the confirmed date. */

import { Badge } from '@simple-module-py/ui/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@simple-module-py/ui/components/ui/table';

import { keys, useT } from '../../utils/i18n';
import type { Subscriber } from '../../utils/types';

const copy = keys.newsletter.subscribers;

export const SUBSCRIBER_STATUS_LABELS: Record<string, string> = {
  pending: copy.status.pending,
  confirmed: copy.status.confirmed,
  unsubscribed: copy.status.unsubscribed,
};

const VARIANT: Record<string, 'default' | 'secondary' | 'outline'> = {
  confirmed: 'default',
  pending: 'outline',
  unsubscribed: 'secondary',
};

interface Props {
  items: Subscriber[];
  tagLabels: Record<string, string>;
  onOpen: (s: Subscriber) => void;
}

export function SubscriberTable({ items, tagLabels, onOpen }: Props) {
  const { t, locale } = useT();
  const date = new Intl.DateTimeFormat(locale, { dateStyle: 'medium' });
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t(copy.email)}</TableHead>
          <TableHead>{t(copy.name)}</TableHead>
          <TableHead>{t(copy.status.label)}</TableHead>
          <TableHead>{t(copy.tags)}</TableHead>
          <TableHead>{t(copy.confirmed_at)}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((s) => (
          <TableRow key={s.uuid} className="cursor-pointer" onClick={() => onOpen(s)}>
            <TableCell className="font-medium">
              <button
                type="button"
                className="text-left hover:underline"
                onClick={(e) => {
                  e.stopPropagation();
                  onOpen(s);
                }}
              >
                {s.email}
              </button>
            </TableCell>
            <TableCell>{[s.first_name, s.last_name].filter(Boolean).join(' ')}</TableCell>
            <TableCell>
              <div className="flex flex-wrap gap-1">
                <Badge variant={VARIANT[s.status] ?? 'secondary'}>
                  {SUBSCRIBER_STATUS_LABELS[s.status]
                    ? t(SUBSCRIBER_STATUS_LABELS[s.status])
                    : s.status}
                </Badge>
                {s.suppressed && <Badge variant="destructive">{t(copy.suppressed)}</Badge>}
                {s.trashed && <Badge variant="outline">{t(copy.trashed)}</Badge>}
              </div>
            </TableCell>
            <TableCell>
              <div className="flex flex-wrap gap-1">
                {s.tags.map((tag) => (
                  <Badge key={tag} variant="secondary">
                    {tagLabels[tag] ?? tag}
                  </Badge>
                ))}
              </div>
            </TableCell>
            <TableCell className="text-muted-foreground">
              {s.confirmed_at ? date.format(new Date(s.confirmed_at)) : ''}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
