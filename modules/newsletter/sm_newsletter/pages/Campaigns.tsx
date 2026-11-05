import { Head, usePage } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { Skeleton } from '@simple-module-py/ui/components/ui/skeleton';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import type { SharedProps } from '@simple-module-py/ui/types';

import { CampaignTable, STATUS_LABELS } from '../ui/components/campaigns/CampaignTable';
import { NewCampaignDialog } from '../ui/components/campaigns/NewCampaignDialog';
import { useCampaignList } from '../ui/hooks/useCampaignList';
import { keys, useT } from '../ui/utils/i18n';

interface CampaignsProps {
  can_edit?: boolean;
  can_send?: boolean;
}

/** The campaign list: search, status filter and a table. Creating and deleting need `can_edit`. */
export default function Campaigns() {
  const { t } = useT();
  const copy = keys.newsletter.campaigns;
  const props = usePage<{ props: SharedProps & CampaignsProps }>().props as unknown as SharedProps &
    CampaignsProps;
  const canEdit = props.can_edit === true;
  const list = useCampaignList();
  const { items, total, offset } = list;

  return (
    <PageShell
      title={t(copy.title)}
      description={t(copy.description)}
      actions={canEdit ? <NewCampaignDialog /> : undefined}
    >
      <Head title={t(copy.title)} />
      {list.error && <p className="mb-4 text-sm text-destructive">{list.error}</p>}

      <div className="mb-4 flex flex-wrap gap-2">
        <Input
          type="search"
          className="max-w-xs"
          aria-label={t(copy.search_label)}
          placeholder={t(copy.search_placeholder)}
          value={list.q}
          onChange={(e) => list.setQ(e.target.value)}
        />
        <NativeSelect
          aria-label={t(copy.status_label)}
          value={list.status}
          onChange={(e) => list.setStatus(e.target.value)}
        >
          <option value="">{t(copy.status_all)}</option>
          {Object.entries(STATUS_LABELS).map(([status, label]) => (
            <option key={status} value={status}>
              {t(label)}
            </option>
          ))}
        </NativeSelect>
      </div>

      {items === null ? (
        <div role="status" aria-label={t(copy.loading)} className="space-y-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : items.length === 0 ? (
        <div className="rounded-lg border border-dashed p-8 text-center">
          {list.filtered ? (
            <>
              <p className="font-medium">{t(copy.no_match)}</p>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="mt-3"
                onClick={() => {
                  list.setQ('');
                  list.setStatus('');
                }}
              >
                {t(copy.clear)}
              </Button>
            </>
          ) : (
            <>
              <p className="font-medium">{t(copy.empty_title)}</p>
              <p className="mt-1 text-sm text-muted-foreground">{t(copy.empty_description)}</p>
            </>
          )}
        </div>
      ) : (
        <>
          <CampaignTable items={items} canEdit={canEdit} onDeleted={list.reload} />
          <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
            <span>{t(copy.showing, { from: offset + 1, to: offset + items.length, total })}</span>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={offset === 0}
                onClick={list.previousPage}
              >
                {t(copy.previous)}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={!list.hasNext}
                onClick={list.nextPage}
              >
                {t(copy.next)}
              </Button>
            </div>
          </div>
        </>
      )}
    </PageShell>
  );
}

Campaigns.layout = [AuthenticatedLayout];
