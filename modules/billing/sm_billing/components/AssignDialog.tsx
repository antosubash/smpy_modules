import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@simple-module-py/ui/components/ui/dialog';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';
import { useEffect, useState } from 'react';
import { STATUSES, statusLabel } from '../utils/format';
import { keys, useT } from '../utils/i18n';
import type { Plan, SubscriptionRow, SubscriptionStatus } from '../utils/types';

interface Props {
  row: SubscriptionRow | null;
  plans: Plan[];
  busy: boolean;
  onClose: () => void;
  onAssign: (planId: number, status: SubscriptionStatus) => void;
}

/** Manual provider: set an organisation's plan and status by hand. */
export function AssignDialog({ row, plans, busy, onClose, onAssign }: Props) {
  const { t } = useT();
  const choices = plans.filter((p) => !p.archived_at);
  const [planId, setPlanId] = useState<number>(row?.plan_id ?? choices[0]?.id ?? 0);
  const [status, setStatus] = useState<SubscriptionStatus>(row?.status ?? 'active');
  useEffect(() => {
    if (row) {
      setPlanId(row.plan_id);
      setStatus(row.status ?? 'active');
    }
  }, [row]);

  return (
    <Dialog open={row !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {t(keys.billing.assign.title, { name: row?.tenant_name ?? '' })}
          </DialogTitle>
          <DialogDescription>{t(keys.billing.assign.description)}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="assign-plan">{t(keys.billing.assign.plan)}</Label>
            <NativeSelect
              id="assign-plan"
              value={String(planId)}
              onChange={(e) => setPlanId(Number(e.target.value))}
            >
              {choices.map((p) => (
                <NativeSelectOption key={p.id} value={String(p.id)}>
                  {p.name}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="assign-status">{t(keys.billing.assign.status)}</Label>
            <NativeSelect
              id="assign-status"
              value={status}
              onChange={(e) => setStatus(e.target.value as SubscriptionStatus)}
            >
              {STATUSES.map((s) => (
                <NativeSelectOption key={s} value={s}>
                  {statusLabel(s)}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t(keys.billing.assign.cancel)}
          </Button>
          <Button disabled={busy || !planId} onClick={() => onAssign(planId, status)}>
            {t(keys.billing.assign.assign)}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
