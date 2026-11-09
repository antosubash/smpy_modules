import { Head, Link, usePage } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Skeleton } from '@simple-module-py/ui/components/ui/skeleton';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';

import { campaignsUrl, editorUrl } from '../ui/components/campaigns/urls';
import { LinkTable } from '../ui/components/report/LinkTable';
import { ReportStats } from '../ui/components/report/ReportStats';
import { ReportTimeline } from '../ui/components/report/ReportTimeline';
import { useCampaignReport } from '../ui/hooks/useCampaignReport';
import { keys, useT } from '../ui/utils/i18n';
import { hasStarted } from '../ui/utils/report';

/** The props `web/endpoints/views.py` `campaign_report` renders. */
interface ReportProps {
  campaign_id: number;
  name: string;
}

const copy = keys.newsletter.report;

/** One campaign's report: outcomes, opens and clicks, activity over time and per-link clicks. */
export default function CampaignReport() {
  const { t } = useT();
  const props = usePage().props as unknown as ReportProps;
  const { report, error, reload } = useCampaignReport(props.campaign_id);
  const title = t(copy.title, { name: props.name });

  return (
    <PageShell
      title={title}
      actions={
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" asChild>
            <Link href={campaignsUrl}>{t(copy.back)}</Link>
          </Button>
          <Button variant="outline" asChild>
            <Link href={editorUrl(props.campaign_id)}>{t(copy.open_editor)}</Link>
          </Button>
          <Button variant="outline" onClick={() => void reload()}>
            {t(copy.refresh)}
          </Button>
        </div>
      }
    >
      <Head title={title} />
      {error && <p className="mb-4 text-sm text-destructive">{error}</p>}
      {report === null ? (
        !error && (
          <div role="status" aria-label={t(copy.loading)} className="space-y-2">
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        )
      ) : !hasStarted(report) ? (
        <p className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
          {t(copy.not_started)}
        </p>
      ) : (
        <div className="space-y-8">
          <ReportStats report={report} />
          <ReportTimeline bucket={report.bucket} points={report.timeline} />
          <LinkTable links={report.links} trackingOff={!report.tracking_clicks} />
        </div>
      )}
    </PageShell>
  );
}

CampaignReport.layout = [AuthenticatedLayout];
