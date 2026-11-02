import { Button } from '@simple-module-py/ui/components/ui/button';
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

import { listGroups } from '../../utils/api-groups';
import { errorText } from '../../utils/api-net';
import {
  createPrompt,
  deletePrompt,
  listPrompts,
  runPrompt,
  updatePrompt,
} from '../../utils/api-prompts';
import { keys, useT } from '../../utils/i18n';
import type { GroupItem } from '../../utils/types';
import type { Prompt, PromptFields } from '../../utils/types-prompts';
import { PresetPicker } from './PresetPicker';
import { PromptForm } from './PromptForm';
import { PromptRow, type RunTarget } from './PromptRow';

type View = { mode: 'list' } | { mode: 'create' } | { mode: 'edit'; prompt: Prompt };

const GROUPS_SHOWN = 100;

/**
 * A collection's prompts (the portal's custom pipeline manager): list,
 * create, edit, delete and run them, and apply a preset. ``canEdit`` writes
 * prompts; ``canManage`` (owner or ``images.manage``) also runs them over the
 * whole collection, switches auto-run on and applies presets.
 */
export function PromptsTab({
  collectionId,
  canEdit,
  canManage,
  imageCount = null,
}: {
  collectionId: string;
  canEdit: boolean;
  canManage: boolean;
  /** The collection's images: the most an image prompt's run can request. */
  imageCount?: number | null;
}) {
  const { t } = useT();
  const [prompts, setPrompts] = useState<Prompt[] | null>(null);
  const [groups, setGroups] = useState<GroupItem[]>([]);
  const [view, setView] = useState<View>({ mode: 'list' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Per prompt, how many runs were launched here: its results panel re-reads.
  const [launched, setLaunched] = useState<Record<string, number>>({});

  const load = useCallback(async () => {
    try {
      setPrompts(await listPrompts(collectionId));
      setError(null);
    } catch (e) {
      setError(errorText(e));
    }
  }, [collectionId]);

  useEffect(() => {
    void load();
  }, [load]);

  const hasGroupPrompt = prompts?.some((p) => p.scope === 'group') ?? false;
  useEffect(() => {
    if (!hasGroupPrompt) return; // names for the results, and the editor's group picker
    listGroups(collectionId, null, GROUPS_SHOWN)
      .then((page) => setGroups(page.items))
      .catch(() => setGroups([]));
  }, [collectionId, hasGroupPrompt]);

  const act = async (work: () => Promise<unknown>, done?: string) => {
    setBusy(true);
    try {
      await work();
      if (done) toast(done);
    } catch (e) {
      toast.error(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const save = (fields: PromptFields) =>
    act(async () => {
      if (view.mode === 'edit') await updatePrompt(view.prompt.id, fields);
      else await createPrompt(collectionId, fields);
      setView({ mode: 'list' });
      await load();
    }, t(keys.images.prompts.saved));

  const run = (prompt: Prompt, target: RunTarget) =>
    act(async () => {
      const { requested } = await runPrompt(prompt.id, target.scope, { groupIds: target.groupIds });
      setLaunched((n) => ({ ...n, [prompt.id]: (n[prompt.id] ?? 0) + 1 }));
      toast(
        requested === null
          ? t(keys.images.prompts.run.queued)
          : t(keys.images.prompts.run.started, { count: requested }),
      );
    });

  const banner = error && (
    <p className="text-sm text-destructive" role="alert" data-testid="images-prompts-error">
      {error}
    </p>
  );
  // Only a failed first load replaces the tab; a failed reload keeps the list.
  if (prompts === null) return banner || null;

  if (view.mode !== 'list') {
    return (
      <PromptForm
        initial={view.mode === 'edit' ? view.prompt : undefined}
        imagePrompts={prompts.filter((p) => p.scope === 'image')}
        canManage={canManage}
        busy={busy}
        onSubmit={(fields) => void save(fields)}
        onCancel={() => setView({ mode: 'list' })}
      />
    );
  }

  return (
    <div className="space-y-4" data-testid="images-prompts">
      {banner}
      <p className="text-sm text-muted-foreground">{t(keys.images.prompts.intro)}</p>
      <div className="flex flex-wrap items-end justify-between gap-4">
        {canManage ? (
          <PresetPicker collectionId={collectionId} onApplied={() => void load()} />
        ) : (
          <span />
        )}
        {canEdit && (
          <Button
            type="button"
            data-testid="images-prompt-new"
            onClick={() => setView({ mode: 'create' })}
          >
            {t(keys.images.prompts.new)}
          </Button>
        )}
      </div>
      {prompts.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t(keys.images.prompts.empty)}</p>
      ) : (
        <ul className="space-y-3">
          {prompts.map((p) => (
            <PromptRow
              key={p.id}
              prompt={p}
              canEdit={canEdit}
              canManage={canManage}
              groups={groups}
              runCount={
                p.scope === 'group'
                  ? groups.length < GROUPS_SHOWN
                    ? groups.length
                    : null
                  : imageCount
              }
              busy={busy}
              onEdit={() => setView({ mode: 'edit', prompt: p })}
              onDelete={async () => {
                await deletePrompt(p.id);
                toast(t(keys.images.prompts.deleted));
                await load();
              }}
              onRun={(target) => void run(p, target)}
              version={launched[p.id] ?? 0}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
