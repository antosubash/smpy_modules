import { Button } from '@simple-module-py/ui/components/ui/button';
import { useState } from 'react';
import { keys, useT } from '../utils/i18n';
import { reportCsv } from '../utils/reportExport';
import type { Filters, Property, Report } from '../utils/types';

export function ReportExport({
  property,
  report,
  filters,
  busy,
}: {
  property: Property;
  report: Report | null;
  filters: Filters;
  busy: boolean;
}) {
  const { t } = useT();
  const [failed, setFailed] = useState(false);
  const download = () => {
    if (!report || busy) return;
    setFailed(false);
    try {
      const blob = new Blob([reportCsv(property, filters, report)], {
        type: 'text/csv;charset=utf-8',
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      const parts = [property.id, filters.start, filters.end].map((part) =>
        part.replace(/[^a-zA-Z0-9_-]/g, '_'),
      );
      anchor.href = url;
      anchor.download = `analytics-${parts.join('-')}.csv`;
      document.body.append(anchor);
      try {
        anchor.click();
      } finally {
        anchor.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    } catch {
      setFailed(true);
    }
  };
  return (
    <div>
      <Button
        variant="ghost"
        size="sm"
        disabled={!report || busy}
        onClick={download}
        title={t(keys.analytics.ui.export_help)}
      >
        {t(keys.analytics.ui.export_csv)}
      </Button>
      {failed && (
        <p role="alert" className="text-xs text-destructive">
          {t(keys.analytics.ui.export_failed)}
        </p>
      )}
    </div>
  );
}
