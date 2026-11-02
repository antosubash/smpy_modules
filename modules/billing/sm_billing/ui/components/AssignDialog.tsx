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
import { useEffect, useMemo, useState } from 'react';
import { clipName, STATUSES, statusLabel } from '../utils/format';
import { keys, useT } from '../utils/i18n';
import type { Plan, SubjectMode, SubscriptionRow, SubscriptionStatus } from '../utils/types';

interface Props {
  row: SubscriptionRow | null;
  plans: Plan[];
  busy: boolean;
  onClose: () => void;
  onAssign: (planId: number, status: SubscriptionStatus) => void;
  /** "user": per-seat plans are left out — a user has no seats (#274). */
  subjectMode?: SubjectMode;
}

/**
 * The row's plan when the picker offers it, else the first choice: an archived
 * plan, or a per-seat one for a user, is not in the list to be preselected.
 */
export function offeredPlan(choices: Plan[], current: number | undefined): number {
  return choices.some((p) => p.id === current) ? (current as number) : (choices[0]?.id ?? 0);
}

/** Manual provider: set an organisation's (or a user's) plan and status by hand. */
export function AssignDialog({
  row,
  plans,
  busy,
  onClose,
  onAssign,
  subjectMode = 'tenant',
}: Props) {
  const { t } = useT();
  const byUser = subjectMode === 'user';
  const choices = useMemo(
    () => plans.filter((p) => !p.archived_at && !(byUser && p.pricing_model === 'per_seat')),
    [plans, byUser],
  );
  const [planId, setPlanId] = useState<number>(() => offeredPlan(choices, row?.plan_id));
  const [status, setStatus] = useState<SubscriptionStatus>(row?.status ?? 'active');
  useEffect(() => {
    if (row) {
      setPlanId(offeredPlan(choices, row.plan_id));
      setStatus(row.status ?? 'active');
    }
  }, [row, choices]);

  return (
    <Dialog open={row !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {t(keys.billing.assign.title, { name: clipName(row?.tenant_name ?? '') })}
          </DialogTitle>
          <DialogDescription>
            {t(byUser ? keys.billing.assign.description_user : keys.billing.assign.description)}
          </DialogDescription>
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
        {choices.length === 0 && (
          <p role="status" className="text-sm text-muted-foreground">
            {t(keys.billing.assign.no_plans)}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t(keys.billing.assign.cancel)}
          </Button>
          <Button
            disabled={busy || choices.length === 0 || !planId}
            onClick={() => onAssign(planId, status)}
          >
            {t(keys.billing.assign.assign)}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
