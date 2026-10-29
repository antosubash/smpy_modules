import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { useState } from 'react';

import { keys, useT } from '../../utils/i18n';
import type { GroupItem } from '../../utils/types';
import type { Prompt, PromptRunScope } from '../../utils/types-prompts';
import { ConfirmDialog } from '../ConfirmDialog';
import { GroupResults } from './GroupResults';

const RUN = {
  missing: keys.images.prompts.run.missing,
  stale: keys.images.prompts.run.stale,
  all: keys.images.prompts.run.all,
} satisfies Record<PromptRunScope, string>;

const SCOPES = Object.keys(RUN) as PromptRunScope[];

export type RunTarget = { scope: PromptRunScope; groupIds?: string[] };

/**
 * One prompt: what it is, and what this person may do with it.
 *
 * * Edit and delete - ``can_edit``.
 * * Running over the whole collection (each scope) - the owner or a manager
 *   only, like a pipeline restart: it spends AI requests without bound.
 * * A group prompt on one chosen group, where missing or stale - any editor.
 */
export function PromptRow({
  prompt,
  canEdit,
  canManage,
  groups,
  busy,
  onEdit,
  onDelete,
  onRun,
  version = 0,
}: {
  prompt: Prompt;
  canEdit: boolean;
  canManage: boolean;
  groups: GroupItem[];
  busy: boolean;
  onEdit: () => void;
  onDelete: () => Promise<void>;
  onRun: (target: RunTarget) => void;
  /** Bumped after each run of this prompt is launched (re-reads its results). */
  version?: number;
}) {
  const { t } = useT();
  const [group, setGroup] = useState('');
  const [results, setResults] = useState(false);
  const isGroup = prompt.scope === 'group';
  return (
    <li className="space-y-2 rounded-md border p-3" data-testid={`images-prompt-${prompt.id}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{prompt.name}</span>
        <Badge variant="outline">
          {t(isGroup ? keys.images.prompts.scope.group : keys.images.prompts.scope.image)}
        </Badge>
        {prompt.auto_run && <Badge>{t(keys.images.prompts.badge_auto)}</Badge>}
        <span className="text-xs text-muted-foreground">
          {t(keys.images.prompts.revision, { revision: prompt.revision })}
        </span>
      </div>
      <p className="line-clamp-2 text-sm text-muted-foreground">{prompt.instruction}</p>
      <div className="flex flex-wrap items-center gap-2">
        {canManage &&
          SCOPES.map((scope) => (
            <Button
              key={scope}
              type="button"
              size="sm"
              variant="outline"
              disabled={busy}
              data-testid={`images-prompt-run-${scope}-${prompt.id}`}
              onClick={() => onRun({ scope })}
            >
              {t(RUN[scope])}
            </Button>
          ))}
        {canEdit && isGroup && groups.length > 0 && (
          <>
            <NativeSelect
              aria-label={t(keys.images.prompts.run.pick_group)}
              value={group}
              data-testid={`images-prompt-group-${prompt.id}`}
              onChange={(e) => setGroup(e.target.value)}
            >
              <option value="">{t(keys.images.prompts.run.pick_group)}</option>
              {groups.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name || g.key}
                </option>
              ))}
            </NativeSelect>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={busy || group === ''}
              data-testid={`images-prompt-run-group-${prompt.id}`}
              onClick={() => onRun({ scope: 'stale', groupIds: [group] })}
            >
              {t(keys.images.prompts.run.on_group)}
            </Button>
          </>
        )}
        {isGroup && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            aria-expanded={results}
            data-testid={`images-prompt-results-${prompt.id}`}
            onClick={() => setResults((open) => !open)}
          >
            {t(results ? keys.images.prompts.results.hide : keys.images.prompts.results.show)}
          </Button>
        )}
        {canEdit && (
          <>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              data-testid={`images-prompt-edit-${prompt.id}`}
              onClick={onEdit}
            >
              {t(keys.images.prompts.edit)}
            </Button>
            <ConfirmDialog
              trigger={
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  data-testid={`images-prompt-delete-${prompt.id}`}
                >
                  {t(keys.images.prompts.delete)}
                </Button>
              }
              title={t(keys.images.prompts.delete_title)}
              description={t(keys.images.prompts.delete_body)}
              confirmLabel={t(keys.images.prompts.delete_confirm)}
              onConfirm={onDelete}
            />
          </>
        )}
      </div>
      {results && <GroupResults promptId={prompt.id} groups={groups} version={version} />}
    </li>
  );
}
