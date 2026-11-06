import { Head, usePage } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import type { SharedProps } from '@simple-module-py/ui/types';
import { useCallback, useEffect, useRef, useState } from 'react';

import { SegmentEditorDialog } from '../ui/components/segments/SegmentEditorDialog';
import { SegmentTable } from '../ui/components/segments/SegmentTable';
import { useListFields } from '../ui/hooks/useListFields';
import { api, errorMessage } from '../ui/utils/api';
import { keys, useT } from '../ui/utils/i18n';
import type { Segment } from '../ui/utils/types';

interface SegmentsProps {
  can_edit?: boolean;
}

/** Saved segments of one list, with a rule editor. Creating, editing and deleting need `can_edit`. */
export default function Segments() {
  const { t } = useT();
  const tRef = useRef(t);
  tRef.current = t;
  const copy = keys.newsletter.segments;
  const props = usePage<{ props: SharedProps & SegmentsProps }>().props as unknown as SharedProps &
    SegmentsProps;
  const canEdit = props.can_edit === true;

  const [lists, setLists] = useState<string[] | null>(null);
  const [listKey, setListKey] = useState('');
  const [items, setItems] = useState<Segment[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Segment | null>(null);
  const [open, setOpen] = useState(false);
  const { fields, error: fieldsError } = useListFields(listKey);

  useEffect(() => {
    api
      .lists()
      .then((l) => {
        setLists(l);
        setListKey((k) => k || (l[0] ?? ''));
      })
      .catch((e) => setError(errorMessage(e, tRef.current)));
  }, []);

  const reload = useCallback(() => {
    if (!listKey) return;
    api
      .listSegments(listKey)
      .then((s) => {
        setItems(s);
        setError(null);
      })
      .catch((e) => setError(errorMessage(e, tRef.current)));
  }, [listKey]);

  useEffect(() => {
    setItems(null);
    reload();
  }, [reload]);

  const ready = fields !== null;
  return (
    <PageShell
      title={t(copy.title)}
      description={t(copy.description)}
      actions={
        canEdit ? (
          <Button
            type="button"
            disabled={!ready || !listKey}
            onClick={() => {
              setEditing(null);
              setOpen(true);
            }}
          >
            {t(copy.new)}
          </Button>
        ) : undefined
      }
    >
      <Head title={t(copy.title)} />
      {(error ?? fieldsError) && (
        <p role="alert" className="mb-4 text-sm text-destructive">
          {error ?? fieldsError}
        </p>
      )}

      <div className="mb-4 flex items-center gap-2">
        <Label htmlFor="newsletter-segments-list">{t(copy.list_label)}</Label>
        <NativeSelect
          id="newsletter-segments-list"
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

      {items !== null && items.length === 0 ? (
        <div className="rounded-lg border border-dashed p-8 text-center">
          <p className="font-medium">{t(copy.empty)}</p>
        </div>
      ) : (
        items !== null && (
          <SegmentTable
            items={items}
            fields={fields ?? []}
            canEdit={canEdit}
            onEdit={(s) => {
              setEditing(s);
              setOpen(true);
            }}
            onDeleted={reload}
          />
        )
      )}

      {ready && canEdit && (
        <SegmentEditorDialog
          listKey={listKey}
          segment={editing}
          fields={fields}
          open={open}
          onOpenChange={setOpen}
          onSaved={reload}
        />
      )}
    </PageShell>
  );
}

Segments.layout = [AuthenticatedLayout];
