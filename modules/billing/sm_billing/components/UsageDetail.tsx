import { Button } from '@simple-module-py/ui/components/ui/button';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@simple-module-py/ui/components/ui/sheet';
import { RefreshCw, SlidersHorizontal } from 'lucide-react';
import { useMemo, useState } from 'react';
import { toast } from 'sonner';
import { USAGE_API, useUsageDetail } from '../hooks/useUsageDetail';
import { api } from '../utils/api';
import { clipName } from '../utils/format';
import { keys, useT } from '../utils/i18n';
import type { MeterInfo, UsageHold, UsageRow } from '../utils/types';
import { meterLabel } from '../utils/usage';
import { AdjustDialog } from './AdjustDialog';
import { UsageHolds } from './UsageHolds';
import { UsageLedger } from './UsageLedger';

interface Props {
  row: UsageRow | null;
  meters: MeterInfo[];
  csrf: string;
  canManage: boolean;
  onClose: () => void;
  /** Something changed the counters: the table behind the drawer reloads. */
  onChanged: () => void;
}

/**
 * One organisation's usage: the ledger, its open holds (with Release), a
 * Recount for each gauge and the Adjust dialog for counters — the writes
 * only with ``billing.platform.manage``.
 */
export function UsageDetail({ row, meters, csrf, canManage, onClose, onChanged }: Props) {
  const { t } = useT();
  const c = keys.billing.admin_usage;
  const tenantId = row?.tenant_id ?? null;
  const detail = useUsageDetail(tenantId, csrf, row?.meter ?? '');
  const [busy, setBusy] = useState(false);
  const [adjusting, setAdjusting] = useState(false);
  const counters = useMemo(() => meters.filter((m) => m.kind === 'counter'), [meters]);
  const gauges = useMemo(() => meters.filter((m) => m.kind === 'gauge'), [meters]);
  const base = tenantId ? `${USAGE_API}/${encodeURIComponent(tenantId)}` : '';

  async function run(work: () => Promise<void>) {
    setBusy(true);
    try {
      await work();
      detail.refresh();
      onChanged();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const release = (hold: UsageHold) =>
    run(async () => {
      const { released } = await api<{ released: boolean }>(
        `${USAGE_API}/holds/${encodeURIComponent(hold.id)}/release`,
        csrf,
        { body: {} },
      );
      if (released) toast.success(t(c.holds.released));
      else toast.info(t(c.holds.already_settled));
    });

  const recount = (meter: MeterInfo) =>
    run(async () => {
      const { in_use } = await api<{ in_use: number }>(`${base}/recount`, csrf, {
        body: { meter: meter.key },
      });
      toast.success(
        t(c.recount.done, { meter: meterLabel(meter.label_key, meter.key), value: in_use }),
      );
    });

  const adjust = (meter: string, quantity: number, reason: string) =>
    run(async () => {
      const { used } = await api<{ used: number }>(`${base}/adjust`, csrf, {
        body: { meter, quantity, reason },
      });
      const info = counters.find((m) => m.key === meter);
      toast.success(
        t(c.adjust.done, { meter: info ? meterLabel(info.label_key, meter) : meter, used }),
      );
      setAdjusting(false);
    });

  const initialAdjust = counters.some((m) => m.key === detail.meter) ? detail.meter : '';

  return (
    <Sheet open={row !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-3xl">
        <SheetHeader>
          <SheetTitle>{t(c.detail.title, { name: clipName(row?.tenant_name ?? '') })}</SheetTitle>
          <SheetDescription>{t(c.detail.description)}</SheetDescription>
        </SheetHeader>
        <div className="space-y-6 px-4 pb-6">
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="detail-meter">{t(c.filters.meter)}</Label>
              <NativeSelect
                id="detail-meter"
                value={detail.meter}
                onChange={(e) => detail.setMeter(e.target.value)}
              >
                <NativeSelectOption value="">{t(c.filters.all_meters)}</NativeSelectOption>
                {meters.map((m) => (
                  <NativeSelectOption key={m.key} value={m.key}>
                    {meterLabel(m.label_key, m.key)}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </div>
            {canManage && counters.length > 0 && (
              <Button variant="outline" disabled={busy} onClick={() => setAdjusting(true)}>
                <SlidersHorizontal aria-hidden="true" />
                {t(c.adjust.action)}
              </Button>
            )}
            {canManage &&
              gauges.map((g) => (
                <Button key={g.key} variant="outline" disabled={busy} onClick={() => recount(g)}>
                  <RefreshCw aria-hidden="true" />
                  {t(c.recount.action, { meter: meterLabel(g.label_key, g.key) })}
                </Button>
              ))}
          </div>
          <UsageHolds holds={detail.holds} canManage={canManage} busy={busy} onRelease={release} />
          <UsageLedger
            ledger={detail.ledger}
            kind={detail.kind}
            onKind={detail.setKind}
            onPage={detail.setPage}
          />
        </div>
      </SheetContent>
      <AdjustDialog
        open={adjusting}
        meters={counters}
        initialMeter={initialAdjust}
        busy={busy}
        onClose={() => setAdjusting(false)}
        onSubmit={adjust}
      />
    </Sheet>
  );
}
