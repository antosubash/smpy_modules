import { Button } from '@simple-module-py/ui/components/ui/button';

import { keys, useT } from '../../utils/i18n';

interface Props {
  missing: boolean;
  kind?: 'page' | 'layout';
  busy: boolean;
  onReload: () => void;
  onOverwrite: () => Promise<void>;
}

export function PageConflict({ missing, busy, onReload, onOverwrite, kind = 'page' }: Props) {
  const { t } = useT();
  const conflictKey =
    kind === 'layout'
      ? keys.pagebuilder.errors.layout_conflict
      : keys.pagebuilder.errors.page_conflict;
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-3 border-b bg-amber-50 px-4 py-3 text-sm text-amber-900"
    >
      <span className="min-w-0">
        {t(missing ? keys.pagebuilder.errors.page_gone : conflictKey)}
      </span>
      <Button variant="outline" size="sm" disabled={busy} onClick={onReload}>
        {t(keys.pagebuilder.conflict.reload)}
      </Button>
      {!missing && (
        <Button variant="outline" size="sm" disabled={busy} onClick={() => void onOverwrite()}>
          {t(keys.pagebuilder.conflict.overwrite)}
        </Button>
      )}
    </div>
  );
}
