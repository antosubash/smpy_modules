import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { useState } from 'react';

import { regroup } from '../../utils/api-groups';
import { keys, useT } from '../../utils/i18n';
import type { RegroupResult } from '../../utils/types';

/** Group the collection's images by a filename pattern. "Preview" counts what
 *  would change and writes nothing; "Apply" does it (and is safe to repeat). */
export function RegroupPanel({
  collectionId,
  onApplied,
  onClose,
}: {
  collectionId: string;
  onApplied: () => void;
  onClose: () => void;
}) {
  const { t } = useT();
  const text = keys.images.groups.regroup;
  const [pattern, setPattern] = useState('');
  const [reassign, setReassign] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RegroupResult | null>(null);

  const run = async (dryRun: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const done = await regroup(collectionId, { pattern, reassign, dry_run: dryRun });
      setResult(done);
      if (!dryRun) onApplied();
    } catch (e) {
      setResult(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3 rounded-md border p-4" data-testid="images-regroup">
      <h3 className="font-medium">{t(text.title)}</h3>
      <p className="text-xs text-muted-foreground">{t(text.help)}</p>
      <div className="grid gap-2">
        <Label htmlFor="images-regroup-pattern">{t(text.pattern)}</Label>
        <Input
          id="images-regroup-pattern"
          value={pattern}
          maxLength={500}
          className="font-mono"
          onChange={(e) => {
            setPattern(e.target.value);
            setResult(null);
          }}
        />
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={reassign}
          data-testid="images-regroup-reassign"
          onChange={(e) => {
            setReassign(e.target.checked);
            setResult(null);
          }}
        />
        {t(text.reassign)}
      </label>
      {error && (
        <p className="text-sm text-destructive" role="alert" data-testid="images-regroup-error">
          {error}
        </p>
      )}
      {result && (
        <p className="text-sm" role="status" data-testid="images-regroup-result">
          {t(text.result, { ...result })}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="outline"
          disabled={busy || !pattern.trim()}
          data-testid="images-regroup-preview"
          onClick={() => void run(true)}
        >
          {t(text.preview)}
        </Button>
        <Button
          type="button"
          disabled={busy || !pattern.trim()}
          data-testid="images-regroup-apply"
          onClick={() => void run(false)}
        >
          {t(text.apply)}
        </Button>
        <Button type="button" variant="ghost" onClick={onClose}>
          {t(text.close)}
        </Button>
      </div>
    </div>
  );
}
