import { Button } from '@simple-module-py/ui/components/ui/button';

import { keys, useT } from '../../utils/i18n';

interface Props {
  busy: boolean;
  onReload: () => void;
  onOverwrite: () => Promise<void>;
}

export function PageConflict({ busy, onReload, onOverwrite }: Props) {
  const { t } = useT();
  return (
    <div role="alert" className="border-b bg-amber-50 px-4 py-3 text-sm text-amber-900">
      <span>{t(keys.pagebuilder.errors.page_conflict)}</span>
      <Button variant="outline" size="sm" disabled={busy} onClick={onReload}>
        {t(keys.pagebuilder.conflict.reload)}
      </Button>
      <Button variant="outline" size="sm" disabled={busy} onClick={() => void onOverwrite()}>
        {t(keys.pagebuilder.conflict.overwrite)}
      </Button>
    </div>
  );
}
