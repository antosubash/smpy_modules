import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@simple-module-py/ui/components/ui/dialog';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';
import { useEffect, useState } from 'react';
import { keys, useT } from '../utils/i18n';
import type { MeterInfo } from '../utils/types';
import { meterLabel, parseAdjustQuantity } from '../utils/usage';

/** The server's bound on a reason (``metering.schemas.REASON_MAX``). */
export const REASON_MAX = 500;

interface Props {
  open: boolean;
  /** Counter meters only: a gauge is repaired by recounting, not adjusted. */
  meters: MeterInfo[];
  initialMeter: string;
  busy: boolean;
  onClose: () => void;
  /** Where focus goes when the dialog closes (``useReturnFocus``). */
  onCloseAutoFocus?: (event: Event) => void;
  onSubmit: (meter: string, quantity: number, reason: string) => void;
}

/**
 * A signed correction to this period's counter, with a required reason —
 * both are recorded on the ledger's ``adjust`` row with the acting admin.
 */
export function AdjustDialog({
  open,
  meters,
  initialMeter,
  busy,
  onClose,
  onCloseAutoFocus,
  onSubmit,
}: Props) {
  const { t } = useT();
  const c = keys.billing.admin_usage.adjust;
  const [meter, setMeter] = useState(initialMeter);
  const [quantity, setQuantity] = useState('');
  const [reason, setReason] = useState('');
  const [tried, setTried] = useState(false);
  useEffect(() => {
    if (open) {
      setMeter(initialMeter || meters[0]?.key || '');
      setQuantity('');
      setReason('');
      setTried(false);
    }
  }, [open, initialMeter, meters]);

  const parsed = parseAdjustQuantity(quantity);
  const reasonOk = reason.trim().length > 0;
  const submit = () => {
    setTried(true);
    if (parsed === null || !reasonOk || !meter) return;
    onSubmit(meter, parsed, reason.trim());
  };
  const shown = meters.find((m) => m.key === meter);

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent onCloseAutoFocus={onCloseAutoFocus}>
        <DialogHeader>
          <DialogTitle>
            {t(c.title, { meter: shown ? meterLabel(shown.label_key, shown.key) : meter })}
          </DialogTitle>
          <DialogDescription>{t(c.description)}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="adjust-meter">{t(c.meter)}</Label>
              <NativeSelect
                id="adjust-meter"
                value={meter}
                onChange={(e) => setMeter(e.target.value)}
              >
                {meters.map((m) => (
                  <NativeSelectOption key={m.key} value={m.key}>
                    {meterLabel(m.label_key, m.key)}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="adjust-quantity">{t(c.quantity)}</Label>
              <Input
                id="adjust-quantity"
                inputMode="numeric"
                value={quantity}
                aria-invalid={tried && parsed === null}
                aria-describedby="adjust-quantity-hint"
                onChange={(e) => setQuantity(e.target.value)}
              />
              <p id="adjust-quantity-hint" className="text-xs text-muted-foreground">
                {tried && parsed === null ? (
                  <span className="text-destructive">{t(c.quantity_invalid)}</span>
                ) : (
                  t(c.quantity_hint)
                )}
              </p>
            </div>
          </div>
          <div className="min-w-0 space-y-1.5">
            <Label htmlFor="adjust-reason">{t(c.reason)}</Label>
            <Textarea
              id="adjust-reason"
              value={reason}
              maxLength={REASON_MAX}
              // An unbroken string must wrap, not widen the auto-sized field.
              className="max-h-48 wrap-anywhere"
              placeholder={t(c.reason_placeholder)}
              aria-invalid={tried && !reasonOk}
              onChange={(e) => setReason(e.target.value)}
            />
            {tried && !reasonOk && (
              <p className="text-xs text-destructive">{t(c.reason_required)}</p>
            )}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t(c.cancel)}
            </Button>
            <Button type="submit" disabled={busy || !meter}>
              {t(c.submit)}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
