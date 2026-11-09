import { Link } from '@inertiajs/react';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@simple-module-py/ui/components/ui/alert-dialog';
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
import { useState } from 'react';

import { api, errorMessage } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
import type { CampaignSummary } from '../../utils/types';
import { editorUrl } from './urls';

/** Every campaign status's label, as `keys` leaves rather than a template literal. */
export const STATUS_LABELS: Record<string, string> = {
  draft: keys.newsletter.campaigns.status.draft,
  scheduled: keys.newsletter.campaigns.status.scheduled,
  sending: keys.newsletter.campaigns.status.sending,
  paused: keys.newsletter.campaigns.status.paused,
  sent: keys.newsletter.campaigns.status.sent,
  cancelled: keys.newsletter.campaigns.status.cancelled,
};

const STATUS_VARIANT: Record<string, 'default' | 'secondary' | 'outline' | 'destructive'> = {
  draft: 'secondary',
  scheduled: 'outline',
  sending: 'default',
  paused: 'outline',
  sent: 'default',
  cancelled: 'destructive',
};

/** Confirmed delete of one draft. The dialog stays open, with the message, when the server refuses. */
function DeleteDraft({
  campaign,
  onDeleted,
}: {
  campaign: CampaignSummary;
  onDeleted: () => void;
}) {
  const { t } = useT();
  const copy = keys.newsletter.campaigns.delete;
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const change = (next: boolean) => {
    if (pending) return;
    setOpen(next);
    setError(null);
  };

  const run = async () => {
    setPending(true);
    setError(null);
    try {
      await api.deleteCampaign(campaign.id);
      setOpen(false);
      onDeleted();
    } catch (e) {
      setError(errorMessage(e, t));
    } finally {
      setPending(false);
    }
  };

  return (
    <AlertDialog open={open} onOpenChange={change}>
      <AlertDialogTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-label={t(copy.label, { name: campaign.name })}
        >
          {t(copy.confirm)}
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t(copy.title)}</AlertDialogTitle>
          <AlertDialogDescription>
            {t(copy.description, { name: campaign.name })}
          </AlertDialogDescription>
        </AlertDialogHeader>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>{t(copy.cancel)}</AlertDialogCancel>
          <AlertDialogAction
            disabled={pending}
            className="bg-destructive text-white hover:bg-destructive/90"
            // Radix closes on click; the close waits for the request so a refusal stays on screen.
            onClick={(e) => {
              e.preventDefault();
              void run();
            }}
          >
            {pending ? t(copy.working) : t(copy.confirm)}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

interface Props {
  items: CampaignSummary[];
  canEdit: boolean;
  onDeleted: () => void;
}

/** Name (a link to the editor), subject, status, list and last change. Delete is offered on drafts, to editors only. */
export function CampaignTable({ items, canEdit, onDeleted }: Props) {
  const { t, locale } = useT();
  const copy = keys.newsletter.campaigns;
  const date = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' });

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t(copy.columns.name)}</TableHead>
          <TableHead>{t(copy.columns.subject)}</TableHead>
          <TableHead>{t(copy.columns.status)}</TableHead>
          <TableHead>{t(copy.columns.list)}</TableHead>
          <TableHead>{t(copy.columns.updated)}</TableHead>
          {canEdit && (
            <TableHead>
              <span className="sr-only">{t(copy.columns.actions)}</span>
            </TableHead>
          )}
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((c) => (
          <TableRow key={c.id}>
            <TableCell className="font-medium">
              <Link href={editorUrl(c.id)} className="hover:underline">
                {c.name}
              </Link>
            </TableCell>
            <TableCell className="text-muted-foreground">
              {c.subject || t(copy.no_subject)}
            </TableCell>
            <TableCell>
              <Badge variant={STATUS_VARIANT[c.status] ?? 'outline'}>
                {STATUS_LABELS[c.status] ? t(STATUS_LABELS[c.status]) : c.status}
              </Badge>
            </TableCell>
            <TableCell>{c.list_type_key}</TableCell>
            <TableCell className="text-muted-foreground">
              {c.updated_at ? date.format(new Date(c.updated_at)) : t(copy.never)}
            </TableCell>
            {canEdit && (
              <TableCell className="text-right">
                {c.status === 'draft' && <DeleteDraft campaign={c} onDeleted={onDeleted} />}
              </TableCell>
            )}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
