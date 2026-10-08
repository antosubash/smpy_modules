import { Button } from '@simple-module-py/ui/components/ui/button';
import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
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
import type React from 'react';
import { useEffect, useState } from 'react';
import { keys, useT } from '../utils/i18n';
import {
  emptyPlanForm,
  formFromPlan,
  MAX_DESCRIPTION,
  MAX_NAME,
  type PlanForm,
  validatePlanForm,
  withPricingModel,
} from '../utils/plan-form';
import type { Plan, PricingModel } from '../utils/types';
import { LimitRows } from './LimitRows';

interface Props {
  open: boolean;
  plan: Plan | null;
  knownKeys: string[];
  busy: boolean;
  /** A rejection from the API, shown in the dialog's alert area. */
  serverError?: string | null;
  onOpenChange: (open: boolean) => void;
  onSave: (form: PlanForm) => void;
}

function Field({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
    </div>
  );
}

export function PlanEditor({
  open,
  plan,
  knownKeys,
  busy,
  serverError = null,
  onOpenChange,
  onSave,
}: Props) {
  const { t } = useT();
  const c = keys.billing.plan_editor;
  const [form, setForm] = useState<PlanForm>(emptyPlanForm());
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (open) {
      setForm(plan ? formFromPlan(plan) : emptyPlanForm());
      setError(null);
    }
  }, [open, plan]);

  const set = <K extends keyof PlanForm>(key: K, value: PlanForm[K]) =>
    setForm((f) => ({ ...f, [key]: value }));
  const text = (key: keyof PlanForm) => (e: React.ChangeEvent<HTMLInputElement>) =>
    set(key, e.target.value as never);
  const paid = form.pricing_model !== 'free';

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    const problem = validatePlanForm(form);
    setError(problem);
    if (!problem) onSave(form);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <form onSubmit={submit} className="space-y-5">
          <DialogHeader>
            <DialogTitle>
              {plan ? t(c.title_edit, { name: plan.name }) : t(c.title_new)}
            </DialogTitle>
            <DialogDescription>{t(c.description)}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="plan-key" label={t(c.key)}>
              <Input id="plan-key" value={form.key} onChange={text('key')} disabled={!!plan} />
            </Field>
            <Field id="plan-name" label={t(c.name)}>
              <Input
                id="plan-name"
                value={form.name}
                maxLength={MAX_NAME}
                onChange={text('name')}
              />
            </Field>
            <Field id="plan-model" label={t(c.pricing)}>
              <NativeSelect
                id="plan-model"
                value={form.pricing_model}
                onChange={(e) =>
                  setForm((f) => withPricingModel(f, e.target.value as PricingModel))
                }
              >
                <NativeSelectOption value="free">{t(c.model_free)}</NativeSelectOption>
                <NativeSelectOption value="flat">{t(c.model_flat)}</NativeSelectOption>
                <NativeSelectOption value="per_seat">{t(c.model_per_seat)}</NativeSelectOption>
              </NativeSelect>
            </Field>
            <Field id="plan-currency" label={t(c.currency)}>
              <Input id="plan-currency" value={form.currency} onChange={text('currency')} />
            </Field>
            {paid && (
              <>
                <Field id="plan-price-m" label={t(c.price_month)}>
                  <Input
                    id="plan-price-m"
                    placeholder="price_…"
                    value={form.stripe_price_month}
                    onChange={text('stripe_price_month')}
                  />
                </Field>
                <Field id="plan-amount-m" label={t(c.amount_month)}>
                  <Input
                    id="plan-amount-m"
                    value={form.amount_month}
                    onChange={text('amount_month')}
                  />
                </Field>
                <Field id="plan-price-y" label={t(c.price_year)}>
                  <Input
                    id="plan-price-y"
                    placeholder="price_…"
                    value={form.stripe_price_year}
                    onChange={text('stripe_price_year')}
                  />
                </Field>
                <Field id="plan-amount-y" label={t(c.amount_year)}>
                  <Input
                    id="plan-amount-y"
                    value={form.amount_year}
                    onChange={text('amount_year')}
                  />
                </Field>
                <Field id="plan-trial" label={t(c.trial_days)}>
                  <Input id="plan-trial" value={form.trial_days} onChange={text('trial_days')} />
                </Field>
              </>
            )}
            <Field id="plan-order" label={t(c.sort_order)}>
              <Input id="plan-order" value={form.sort_order} onChange={text('sort_order')} />
            </Field>
          </div>
          <Field id="plan-description" label={t(c.description_label)}>
            <Textarea
              id="plan-description"
              value={form.description}
              maxLength={MAX_DESCRIPTION}
              onChange={(e) => set('description', e.target.value)}
            />
          </Field>
          <div className="space-y-1.5">
            <Label>{t(c.limits)}</Label>
            <LimitRows
              rows={form.limits}
              knownKeys={knownKeys}
              onChange={(r) => set('limits', r)}
            />
          </div>
          <Field id="plan-features" label={t(c.features)}>
            <Input id="plan-features" value={form.features} onChange={text('features')} />
          </Field>
          <div className="flex flex-wrap gap-6">
            <Label className="flex items-center gap-2">
              <Checkbox
                checked={form.is_public}
                onCheckedChange={(v) => set('is_public', v === true)}
              />
              {t(c.is_public)}
            </Label>
            <Label className="flex items-center gap-2">
              <Checkbox
                checked={form.is_default}
                disabled={paid}
                onCheckedChange={(v) => set('is_default', v === true)}
              />
              {t(c.is_default)}
            </Label>
          </div>
          {(error ?? serverError) && (
            <p role="alert" className="text-sm text-destructive">
              {error ?? serverError}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t(c.cancel)}
            </Button>
            <Button type="submit" disabled={busy}>
              {plan ? t(c.save) : t(c.create)}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
