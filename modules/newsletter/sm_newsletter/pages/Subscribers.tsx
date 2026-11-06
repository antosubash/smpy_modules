import { Head, Link, usePage } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import type { SharedProps } from '@simple-module-py/ui/types';
import { useEffect, useRef, useState } from 'react';

import { SubscriberFilters } from '../ui/components/subscribers/SubscriberFilters';
import { SubscriberSheet } from '../ui/components/subscribers/SubscriberSheet';
import {
  SUBSCRIBER_STATUS_LABELS,
  SubscriberTable,
} from '../ui/components/subscribers/SubscriberTable';
import { useListFields } from '../ui/hooks/useListFields';
import { PAGE_SIZE, useSubscriberList } from '../ui/hooks/useSubscriberList';
import { api, errorMessage } from '../ui/utils/api';
import { keys, useT } from '../ui/utils/i18n';
import type { Segment } from '../ui/utils/types';

interface SubscribersProps {
  can_edit?: boolean;
  can_manage?: boolean;
  initial_list?: string | null;
}

const STATUSES = ['confirmed', 'pending', 'unsubscribed'] as const;

/** One list's subscribers: tabs by status, filters, a table and a detail sheet.
 *  The search text is component state only: no URL, no router call (C5). */
export default function Subscribers() {
  const { t } = useT();
  const tRef = useRef(t);
  tRef.current = t;
  const copy = keys.newsletter.subscribers;
  const props = usePage<{ props: SharedProps & SubscribersProps }>()
    .props as unknown as SharedProps & SubscribersProps;

  const [lists, setLists] = useState<string[] | null>(null);
  const [listKey, setListKey] = useState('');
  const [segments, setSegments] = useState<Segment[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const { fields, error: fieldsError } = useListFields(listKey);
  const list = useSubscriberList(listKey);

  useEffect(() => {
    api
      .lists()
      .then((l) => {
        setLists(l);
        const wanted = props.initial_list;
        setListKey((k) => k || (wanted && l.includes(wanted) ? wanted : (l[0] ?? '')));
      })
      .catch((e) => setLoadError(errorMessage(e, tRef.current)));
  }, [props.initial_list]);

  useEffect(() => {
    setSegments([]);
    setOpen(null);
    setLoadError(null);
    if (!listKey) return;
    let live = true;
    api
      .listSegments(listKey)
      .then((s) => live && setSegments(s))
      .catch((e) => live && setLoadError(errorMessage(e, tRef.current)));
    return () => {
      live = false;
    };
  }, [listKey]);

  const tagLabels = Object.fromEntries(
    (fields?.find((f) => f.key === 'tags')?.choices ?? []).map((c) => [c.value, c.label]),
  );
  const { items, total, offset } = list;
  const error = list.error ?? loadError ?? fieldsError;
  const tabCount = (id: string) =>
    id === ''
      ? list.counts.pending + list.counts.confirmed + list.counts.unsubscribed
      : list.counts[id as keyof typeof list.counts];

  return (
    <PageShell title={t(copy.title)} description={t(copy.description)}>
      <Head title={t(copy.title)} />
      {error && (
        <p role="alert" className="mb-4 text-sm text-destructive">
          {error}
        </p>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-2">
          <Label htmlFor="newsletter-subscribers-list">{t(copy.list_label)}</Label>
          <NativeSelect
            id="newsletter-subscribers-list"
            value={listKey}
            onChange={(e) => setListKey(e.target.value)}
          >
            {(lists ?? []).map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </NativeSelect>
        </div>
        {list.recordsUrl && (
          <Link href={list.recordsUrl} className="text-sm text-primary underline">
            {t(copy.open_in_records)}
          </Link>
        )}
      </div>

      <div className="mb-4 flex flex-wrap gap-2">
        {(['', ...STATUSES] as const).map((id) => (
          <Button
            key={id || 'all'}
            size="sm"
            variant={list.status === id ? 'default' : 'outline'}
            aria-pressed={list.status === id}
            onClick={() => list.setStatus(id)}
          >
            {`${t(id === '' ? copy.status.all : SUBSCRIBER_STATUS_LABELS[id])} (${tabCount(id)})`}
          </Button>
        ))}
      </div>

      <SubscriberFilters
        q={list.q}
        tag={list.tag}
        segment={list.segment}
        fields={fields}
        segments={segments}
        onQ={list.setQ}
        onTag={list.setTag}
        onSegment={list.setSegment}
      />

      {items !== null && items.length === 0 ? (
        <div className="rounded-lg border border-dashed p-8 text-center">
          <p className="font-medium">{t(copy.empty)}</p>
        </div>
      ) : (
        items !== null && (
          <SubscriberTable items={items} tagLabels={tagLabels} onOpen={(s) => setOpen(s.uuid)} />
        )
      )}

      {items !== null && items.length > 0 && (
        <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
          <span>
            {t(keys.newsletter.campaigns.showing, {
              from: offset + 1,
              to: offset + items.length,
              total,
            })}
          </span>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={offset === 0}
              onClick={() => list.setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              {t(keys.newsletter.campaigns.previous)}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => list.setOffset(offset + PAGE_SIZE)}
            >
              {t(keys.newsletter.campaigns.next)}
            </Button>
          </div>
        </div>
      )}

      {open !== null && (
        <SubscriberSheet
          key={open}
          listKey={listKey}
          uuid={open}
          canEdit={props.can_edit === true}
          canManage={props.can_manage === true}
          onClose={() => setOpen(null)}
          onChanged={list.reload}
        />
      )}
    </PageShell>
  );
}

Subscribers.layout = [AuthenticatedLayout];
