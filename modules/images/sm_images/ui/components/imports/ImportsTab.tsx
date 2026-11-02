import { Button } from '@simple-module-py/ui/components/ui/button';
import { useState } from 'react';

import { useImportJobs } from '../../hooks/useImportJobs';
import { keys, useT } from '../../utils/i18n';
import { ImportWizard } from './ImportWizard';
import { JobRow } from './JobRow';

/** The Imports tab: the wizard behind "New import", and the collection's jobs
 *  with their progress (polled only while one is running) and controls.
 *  `onSettled` runs when a running import finishes, so the gallery reloads. */
export function ImportsTab({
  collectionId,
  canEdit,
  onSettled,
}: {
  collectionId: string;
  canEdit: boolean;
  onSettled?: () => void;
}) {
  const { t } = useT();
  const text = keys.images.imports;
  const imports = useImportJobs(collectionId, true, onSettled);
  const [wizard, setWizard] = useState(false);

  return (
    <div className="space-y-4" data-testid="images-imports">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">{t(text.description)}</p>
        {canEdit && !wizard && (
          <Button type="button" data-testid="images-import-new" onClick={() => setWizard(true)}>
            {t(text.new)}
          </Button>
        )}
      </div>
      {canEdit && wizard && (
        <ImportWizard
          collectionId={collectionId}
          // An import that ran eagerly is done before polling ever sees it active.
          onStarted={() => void imports.reload().then(() => onSettled?.())}
          onClose={() => setWizard(false)}
        />
      )}
      {imports.error && (
        <p className="text-sm text-destructive" role="alert">
          {t(text.refresh_failed)} {imports.error}
        </p>
      )}
      {imports.loading ? (
        <p className="text-sm text-muted-foreground">{t(text.loading)}</p>
      ) : imports.jobs.length === 0 ? (
        <p className="text-sm text-muted-foreground" data-testid="images-imports-empty">
          {t(text.empty)}
        </p>
      ) : (
        <ul className="space-y-3">
          {imports.jobs.map((job) => (
            <JobRow
              key={job.id}
              job={job}
              canEdit={canEdit}
              onControl={imports.control}
              onRemove={imports.remove}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
