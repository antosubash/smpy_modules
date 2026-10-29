import { Button } from '@simple-module-py/ui/components/ui/button';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { applyPreset, listPresets } from '../../utils/api-prompts';
import { keys, type Translate, useT } from '../../utils/i18n';
import type { Preset } from '../../utils/types-prompts';

/** A preset's name from its plugin's catalogue, or its id while untranslated. */
export function presetLabel(t: Translate, preset: Preset): string {
  const label = t(preset.label_key);
  return label && label !== preset.label_key ? label : preset.id;
}

/**
 * Apply one of the installed presets (owner or manager: it can switch
 * auto-run on). Applying again adds nothing, so the button is always safe.
 */
export function PresetPicker({
  collectionId,
  onApplied,
}: {
  collectionId: string;
  onApplied: () => void;
}) {
  const { t } = useT();
  const [presets, setPresets] = useState<Preset[] | null>(null);
  const [chosen, setChosen] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    listPresets()
      .then(setPresets)
      .catch(() => setPresets([]));
  }, []);

  if (presets === null) return null;
  if (presets.length === 0) {
    return <p className="text-sm text-muted-foreground">{t(keys.images.prompts.preset.none)}</p>;
  }

  const apply = async () => {
    setBusy(true);
    try {
      const { created } = await applyPreset(collectionId, chosen);
      toast(
        created.length
          ? t(keys.images.prompts.preset.applied, { count: created.length })
          : t(keys.images.prompts.preset.none_added),
      );
      onApplied();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-wrap items-end gap-2" data-testid="images-preset-picker">
      <div className="grid gap-2">
        <Label htmlFor="images-preset">{t(keys.images.prompts.preset.label)}</Label>
        <NativeSelect id="images-preset" value={chosen} onChange={(e) => setChosen(e.target.value)}>
          <option value="">{t(keys.images.prompts.preset.pick)}</option>
          {presets.map((p) => (
            <option key={p.id} value={p.id}>
              {presetLabel(t, p)}
            </option>
          ))}
        </NativeSelect>
      </div>
      <Button
        type="button"
        variant="outline"
        disabled={busy || chosen === ''}
        data-testid="images-preset-apply"
        onClick={() => void apply()}
      >
        {t(keys.images.prompts.preset.apply)}
      </Button>
    </div>
  );
}
