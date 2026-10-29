import { Button } from '@simple-module-py/ui/components/ui/button';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { useState } from 'react';
import { toast } from 'sonner';
import { errorText } from '../../utils/api-net';
import { listPrompts, runPrompt } from '../../utils/api-prompts';
import { keys, useT } from '../../utils/i18n';
import type { Prompt, PromptRunScope } from '../../utils/types-prompts';

/** What an editor may spend on chosen images: never `all` (that is the owner's
 *  or a manager's, like any unbounded re-run). */
const SCOPES = {
  missing: keys.images.prompts.run.missing,
  stale: keys.images.prompts.run.stale,
} satisfies Partial<Record<PromptRunScope, string>>;

/**
 * "Run prompt…" for the images picked in the gallery: an image-scope prompt
 * of the collection, where its result is missing or outdated.
 */
export function RunOnImages({
  collectionId,
  imageIds,
  onDone,
}: {
  collectionId: string;
  imageIds: string[];
  onDone: () => void;
}) {
  const { t } = useT();
  const [prompts, setPrompts] = useState<Prompt[] | null>(null);
  const [chosen, setChosen] = useState('');
  const [scope, setScope] = useState<keyof typeof SCOPES>('missing');
  const [busy, setBusy] = useState(false);

  const open = async () => {
    try {
      setPrompts((await listPrompts(collectionId)).filter((p) => p.scope === 'image'));
    } catch (e) {
      toast.error(errorText(e));
    }
  };

  const run = async () => {
    setBusy(true);
    try {
      const { requested } = await runPrompt(chosen, scope, { imageIds });
      toast(t(keys.images.prompts.run.started, { count: requested ?? 0 }));
      setPrompts(null);
      onDone();
    } catch (e) {
      toast.error(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  if (prompts === null) {
    return (
      <Button
        type="button"
        size="sm"
        variant="outline"
        disabled={imageIds.length === 0}
        data-testid="images-run-on-images"
        onClick={() => void open()}
      >
        {t(keys.images.prompts.on_images.open)}
      </Button>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="images-run-on-images-form">
      <NativeSelect
        aria-label={t(keys.images.prompts.on_images.prompt)}
        data-testid="images-run-on-images-prompt"
        value={chosen}
        onChange={(e) => setChosen(e.target.value)}
      >
        <option value="">{t(keys.images.prompts.on_images.prompt)}</option>
        {prompts.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </NativeSelect>
      <NativeSelect
        aria-label={t(keys.images.prompts.on_images.scope)}
        data-testid="images-run-on-images-scope"
        value={scope}
        onChange={(e) => setScope(e.target.value as keyof typeof SCOPES)}
      >
        {(Object.keys(SCOPES) as (keyof typeof SCOPES)[]).map((s) => (
          <option key={s} value={s}>
            {t(SCOPES[s])}
          </option>
        ))}
      </NativeSelect>
      <Button
        type="button"
        size="sm"
        disabled={busy || chosen === '' || imageIds.length === 0}
        data-testid="images-run-on-images-go"
        onClick={() => void run()}
      >
        {t(keys.images.prompts.on_images.go, { count: imageIds.length })}
      </Button>
      <Button type="button" size="sm" variant="ghost" onClick={() => setPrompts(null)}>
        {t(keys.images.prompts.cancel)}
      </Button>
    </div>
  );
}
