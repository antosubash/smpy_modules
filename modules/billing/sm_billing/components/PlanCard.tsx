import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@simple-module-py/ui/components/ui/card';
import { cn } from '@simple-module-py/ui/lib/utils';
import { Check } from 'lucide-react';
import { type PlanCta, priceLabel } from '../utils/format';
import { keys, type Translate, useT } from '../utils/i18n';
import type { Interval, Plan } from '../utils/types';

interface Props {
  plan: Plan;
  interval: Interval;
  cta: PlanCta;
  canManage: boolean;
  busy: boolean;
  onChoose: (plan: Plan, cta: PlanCta) => void;
}

const LABEL: Record<PlanCta, string> = {
  current: keys.billing.plan_card.current,
  checkout: keys.billing.plan_card.checkout,
  change: keys.billing.plan_card.change,
  downgrade: keys.billing.plan_card.downgrade,
  unavailable: keys.billing.plan_card.unavailable,
};

function limitLines(plan: Plan, t: Translate): string[] {
  const seats = plan.limits['tenants.seats'];
  const lines = [
    seats === undefined
      ? t(keys.billing.plan_card.unlimited_seats)
      : t(keys.billing.plan_card.up_to_seats, { count: seats }),
  ];
  for (const [key, value] of Object.entries(plan.limits)) {
    if (key !== 'tenants.seats') lines.push(t(keys.billing.plan_card.limit_line, { key, value }));
  }
  return lines;
}

export function PlanCard({ plan, interval, cta, canManage, busy, onChoose }: Props) {
  const { t } = useT();
  const actionable = canManage && cta !== 'current' && cta !== 'unavailable';
  return (
    <Card
      className={cn('flex flex-col', cta === 'current' && 'border-primary ring-1 ring-primary')}
    >
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-2">
          {plan.name}
          {plan.trial_days > 0 && cta === 'checkout' && (
            <Badge variant="secondary">
              {t(keys.billing.plan_card.trial_badge, { days: plan.trial_days })}
            </Badge>
          )}
        </CardTitle>
        <CardDescription className="text-base font-medium text-foreground">
          {priceLabel(plan, interval)}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex-1 space-y-3 text-sm">
        {plan.description && <p className="text-muted-foreground">{plan.description}</p>}
        <ul className="space-y-1.5">
          {[...limitLines(plan, t), ...plan.features].map((line) => (
            <li key={line} className="flex items-start gap-2">
              <Check className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden="true" />
              <span>{line}</span>
            </li>
          ))}
        </ul>
      </CardContent>
      <CardFooter>
        <Button
          className="w-full max-lg:min-h-11"
          variant={cta === 'downgrade' ? 'outline' : 'default'}
          disabled={!actionable || busy}
          onClick={() => onChoose(plan, cta)}
        >
          {t(LABEL[cta])}
        </Button>
      </CardFooter>
    </Card>
  );
}
