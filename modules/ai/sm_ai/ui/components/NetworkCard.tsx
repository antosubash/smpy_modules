import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@simple-module-py/ui/components/ui/card';
import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import { Label } from '@simple-module-py/ui/components/ui/label';

import { keys, useT } from '../utils/i18n';

/** The `allow_private_base_url` switch (#347). Saved with the slots; changing
 * it needs `settings.edit`, so without that it is shown read-only. */
export function NetworkCard({
  allowPrivate,
  canChange,
  busy,
  onChange,
}: {
  allowPrivate: boolean;
  canChange: boolean;
  busy: boolean;
  onChange: (next: boolean) => void;
}) {
  const { t } = useT();
  const n = keys.ai.network;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t(n.title)}</CardTitle>
        <CardDescription>{t(n.description)}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        <Label className="flex items-center gap-2 font-normal">
          <Checkbox
            id="ai-allow-private"
            checked={allowPrivate}
            disabled={busy || !canChange}
            onCheckedChange={(v) => onChange(v === true)}
          />
          {t(n.allow_private)}
        </Label>
        <p className="text-xs text-muted-foreground">{t(n.allow_private_hint)}</p>
        {!canChange && (
          <p data-testid="ai-allow-private-locked" className="text-xs text-muted-foreground">
            {t(n.needs_settings_edit)}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
