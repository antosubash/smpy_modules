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
  current: 'Current plan',
  checkout: 'Subscribe',
  change: 'Switch to this plan',
  downgrade: 'Downgrade at period end',
  unavailable: 'Not available',
};

function limitLines(plan: Plan): string[] {
  const seats = plan.limits['tenants.seats'];
  const lines = [seats === undefined ? 'Unlimited seats' : `Up to ${seats} seats`];
  for (const [key, value] of Object.entries(plan.limits)) {
    if (key !== 'tenants.seats') lines.push(`${key}: ${value}`);
  }
  return lines;
}

export function PlanCard({ plan, interval, cta, canManage, busy, onChoose }: Props) {
  const actionable = canManage && cta !== 'current' && cta !== 'unavailable';
  return (
    <Card
      className={cn('flex flex-col', cta === 'current' && 'border-primary ring-1 ring-primary')}
    >
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-2">
          {plan.name}
          {plan.trial_days > 0 && cta === 'checkout' && (
            <Badge variant="secondary">{plan.trial_days}-day trial</Badge>
          )}
        </CardTitle>
        <CardDescription className="text-base font-medium text-foreground">
          {priceLabel(plan, interval)}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex-1 space-y-3 text-sm">
        {plan.description && <p className="text-muted-foreground">{plan.description}</p>}
        <ul className="space-y-1.5">
          {[...limitLines(plan), ...plan.features].map((line) => (
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
          {LABEL[cta]}
        </Button>
      </CardFooter>
    </Card>
  );
}
