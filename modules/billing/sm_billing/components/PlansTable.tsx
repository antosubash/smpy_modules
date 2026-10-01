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
import type { Plan } from '../utils/types';

interface Props {
  plans: Plan[];
  canManage: boolean;
  onEdit: (plan: Plan) => void;
  onArchive: (plan: Plan) => void;
}

const MODEL: Record<Plan['pricing_model'], string> = {
  free: 'Free',
  flat: 'Flat',
  per_seat: 'Per seat',
};

export function PlansTable({ plans, canManage, onEdit, onArchive }: Props) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Plan</TableHead>
          <TableHead>Pricing</TableHead>
          <TableHead>Price</TableHead>
          <TableHead>Seats</TableHead>
          <TableHead className="text-right">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {plans.map((plan) => (
          <TableRow key={plan.id} className={plan.archived_at ? 'opacity-60' : undefined}>
            <TableCell>
              <div className="flex flex-wrap items-center gap-2 font-medium">
                {plan.name}
                {plan.is_default && <Badge>Default</Badge>}
                {!plan.is_public && <Badge variant="outline">Hidden</Badge>}
                {plan.archived_at && <Badge variant="secondary">Archived</Badge>}
              </div>
              <div className="font-mono text-xs text-muted-foreground">{plan.key}</div>
            </TableCell>
            <TableCell>{MODEL[plan.pricing_model]}</TableCell>
            <TableCell className="text-sm">
              {priceLabel(plan, 'month')}
              {plan.stripe_price_year && (
                <div className="text-muted-foreground">{priceLabel(plan, 'year')}</div>
              )}
            </TableCell>
            <TableCell>{plan.limits['tenants.seats'] ?? 'Unlimited'}</TableCell>
            <TableCell className="text-right">
              {canManage && !plan.archived_at && (
                <div className="flex justify-end gap-2">
                  <Button size="sm" variant="outline" onClick={() => onEdit(plan)}>
                    Edit
                  </Button>
                  {!plan.is_default && (
                    <Button size="sm" variant="ghost" onClick={() => onArchive(plan)}>
                      Archive
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
