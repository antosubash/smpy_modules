import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from '@simple-module-py/ui/components/ui/dialog';
import { useState } from 'react';
import { keys, useT } from '../utils/i18n';
import type { GeoStatus, Property, PropertyInput } from '../utils/types';
import { DeleteProperty } from './DeleteProperty';
import { PropertyEditor } from './PropertyEditor';

export function PropertySettings({
  canManage,
  property,
  geo,
  onSave,
  onDelete,
}: {
  canManage: boolean;
  property?: Property;
  geo: GeoStatus | null;
  onSave: (input: PropertyInput, id?: string) => Promise<void>;
  onDelete: () => Promise<void>;
}) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<'new' | 'edit' | null>(null);
  if (!canManage) return null;
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (busy) return;
        setEditing(property ? null : 'new');
        setOpen(next);
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline">
          {t(property ? keys.analytics.ui.manage : keys.analytics.new_property)}
        </Button>
      </DialogTrigger>
      <DialogContent
        className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-2xl"
        showCloseButton={false}
      >
        <DialogTitle>{t(keys.analytics.ui.settings)}</DialogTitle>
        <DialogDescription>{t(keys.analytics.setup_help)}</DialogDescription>
        {editing ? (
          <PropertyEditor
            key={editing === 'edit' ? property?.id : 'new'}
            property={editing === 'edit' ? property : undefined}
            onCancel={() => (property ? setEditing(null) : setOpen(false))}
            onSave={async (input) => {
              setBusy(true);
              try {
                await onSave(input, editing === 'edit' ? property?.id : undefined);
                setOpen(false);
              } finally {
                setBusy(false);
              }
            }}
          />
        ) : (
          <>
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => setEditing('new')}>{t(keys.analytics.new_property)}</Button>
              {property && (
                <Button variant="outline" onClick={() => setEditing('edit')}>
                  {t(keys.analytics.edit)}
                </Button>
              )}
            </div>
            {property && (
              <section className="min-w-0 space-y-2 rounded-md border p-4">
                <h2 className="font-medium">{t(keys.analytics.setup)}</h2>
                <p className="break-all text-xs text-muted-foreground">{property.id}</p>
              </section>
            )}
            {geo && (
              <aside className="space-y-1 text-sm text-muted-foreground">
                <p>
                  {t(
                    !geo.enabled
                      ? keys.analytics.geo_disabled
                      : geo.available
                        ? keys.analytics.geo_ready
                        : keys.analytics.geo_unavailable,
                  )}
                </p>
                {geo.age_days !== null && (
                  <p>{t(keys.analytics.geo_age, { days: geo.age_days })}</p>
                )}
              </aside>
            )}
            {property && (
              <div className="border-t pt-4">
                <DeleteProperty
                  onDelete={async () => {
                    await onDelete();
                    setOpen(false);
                  }}
                />
              </div>
            )}
          </>
        )}
        <div className="flex justify-end">
          <Button variant="outline" disabled={busy} onClick={() => setOpen(false)}>
            {t(keys.analytics.ui.close)}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
