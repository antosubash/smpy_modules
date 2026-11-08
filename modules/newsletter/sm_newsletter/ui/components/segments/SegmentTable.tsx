/** Name, a one-line rule summary and the update time; Edit and Delete for editors. */

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@simple-module-py/ui/components/ui/alert-dialog';
import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@simple-module-py/ui/components/ui/table';
import { useState } from 'react';

import { api, errorMessage } from '../../utils/api';
import { keys, type Translate, useT } from '../../utils/i18n';
import type { ListField, Rule, Segment } from '../../utils/types';
import { OP_LABELS, SIGNUP_FIELD } from './RuleRow';

const copy = keys.newsletter.segments;

function summary(rules: Rule[], fields: ListField[], t: Translate): string {
  if (rules.length === 0) return t(copy.summary_none);
  return rules
    .map((r) => {
      const f = fields.find((x) => x.key === r.field);
      const name = r.field === SIGNUP_FIELD ? t(copy.signup_field) : (f?.label ?? r.field);
      const labelOf = (v: string) => f?.choices.find((c) => c.value === v)?.label ?? v;
      const value = Array.isArray(r.value) ? r.value.map(labelOf).join(', ') : labelOf(r.value);
      return `${name} ${t(OP_LABELS[r.op])} ${value}`;
    })
    .join('; ');
}

interface Props {
  items: Segment[];
  fields: ListField[];
  canEdit: boolean;
  onEdit: (s: Segment) => void;
  onDeleted: () => void;
}

export function SegmentTable({ items, fields, canEdit, onEdit, onDeleted }: Props) {
  const { t, locale } = useT();
  const date = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' });
  const [target, setTarget] = useState<Segment | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = () => {
    if (pending) return;
    setTarget(null);
    setError(null);
  };
  const run = async () => {
    if (!target) return;
    setPending(true);
    setError(null);
    try {
      await api.deleteSegment(target.id);
      setTarget(null);
      onDeleted();
    } catch (e) {
      setError(errorMessage(e, t));
    } finally {
      setPending(false);
    }
  };

  return (
    <>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t(copy.name)}</TableHead>
            <TableHead>{t(copy.rules)}</TableHead>
            <TableHead>{t(copy.updated)}</TableHead>
            <TableHead>
              <span className="sr-only">{t(copy.edit)}</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((s) => (
            <TableRow key={s.id}>
              <TableCell
                className="max-w-xs whitespace-normal break-all font-medium"
                title={s.name}
              >
                {s.name}
              </TableCell>
              <TableCell className="whitespace-normal break-words text-muted-foreground">
                {summary(s.rules, fields, t)}
              </TableCell>
              <TableCell className="text-muted-foreground">
                {s.updated_at ? date.format(new Date(s.updated_at)) : ''}
              </TableCell>
              <TableCell className="text-right">
                {canEdit && (
                  <>
                    <Button type="button" variant="ghost" size="sm" onClick={() => onEdit(s)}>
                      {t(copy.edit)}
                    </Button>
                    <Button type="button" variant="ghost" size="sm" onClick={() => setTarget(s)}>
                      {t(copy.delete)}
                    </Button>
                  </>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <AlertDialog open={target !== null} onOpenChange={(o) => !o && close()}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t(copy.delete_confirm.title)}</AlertDialogTitle>
            <AlertDialogDescription>
              {t(copy.delete_confirm.description, { name: target?.name ?? '' })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={pending}>{t(copy.delete_confirm.keep)}</AlertDialogCancel>
            <AlertDialogAction
              disabled={pending}
              className="bg-destructive text-white hover:bg-destructive/90"
              onClick={(e) => {
                e.preventDefault();
                void run();
              }}
            >
              {t(copy.delete_confirm.confirm)}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
