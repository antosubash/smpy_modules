import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@simple-module-py/ui/components/ui/table';
import { priceLabel } from '../utils/format';
import { keys, useT } from '../utils/i18n';
import type { Plan } from '../utils/types';

interface Props {
  plans: Plan[];
  canManage: boolean;
  onEdit: (plan: Plan) => void;
  onArchive: (plan: Plan) => void;
}

const MODEL: Record<Plan['pricing_model'], string> = {
  free: keys.billing.plans_table.model_free,
  flat: keys.billing.plans_table.model_flat,
  per_seat: keys.billing.plans_table.model_per_seat,
};

export function PlansTable({ plans, canManage, onEdit, onArchive }: Props) {
  const { t } = useT();
  const c = keys.billing.plans_table;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t(c.col_plan)}</TableHead>
          <TableHead>{t(c.col_pricing)}</TableHead>
          <TableHead>{t(c.col_price)}</TableHead>
          <TableHead>{t(c.col_seats)}</TableHead>
          <TableHead className="text-right">{t(c.col_actions)}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {plans.map((plan) => (
          <TableRow key={plan.id} className={plan.archived_at ? 'opacity-60' : undefined}>
            <TableCell>
              <div className="flex flex-wrap items-center gap-2 font-medium">
                {plan.name}
                {plan.is_default && <Badge>{t(c.badge_default)}</Badge>}
                {!plan.is_public && <Badge variant="outline">{t(c.badge_hidden)}</Badge>}
                {plan.archived_at && <Badge variant="secondary">{t(c.badge_archived)}</Badge>}
              </div>
              <div className="font-mono text-xs text-muted-foreground">{plan.key}</div>
            </TableCell>
            <TableCell>{t(MODEL[plan.pricing_model])}</TableCell>
            <TableCell className="text-sm">
              {priceLabel(plan, 'month')}
              {plan.stripe_price_year && (
                <div className="text-muted-foreground">{priceLabel(plan, 'year')}</div>
              )}
            </TableCell>
            <TableCell>{plan.limits['tenants.seats'] ?? t(c.unlimited)}</TableCell>
            <TableCell className="text-right">
              {canManage && !plan.archived_at && (
                <div className="flex justify-end gap-2">
                  <Button size="sm" variant="outline" onClick={() => onEdit(plan)}>
                    {t(c.edit)}
                  </Button>
                  {!plan.is_default && (
                    <Button size="sm" variant="ghost" onClick={() => onArchive(plan)}>
                      {t(c.archive)}
                    </Button>
                  )}
                </div>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
