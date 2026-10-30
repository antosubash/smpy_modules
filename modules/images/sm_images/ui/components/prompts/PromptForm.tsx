import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';
import { useState } from 'react';

import { keys, useT } from '../../utils/i18n';
import type {
  JsonSchema,
  Prompt,
  PromptFields,
  PromptInputs,
  PromptScope,
} from '../../utils/types-prompts';
import { SchemaEditor } from './SchemaEditor';

const SCOPE = {
  image: keys.images.prompts.scope.image,
  group: keys.images.prompts.scope.group,
} satisfies Record<PromptScope, string>;

const INPUTS = {
  images: keys.images.prompts.inputs.images,
  results: keys.images.prompts.inputs.results,
  both: keys.images.prompts.inputs.both,
} satisfies Record<PromptInputs, string>;

const STARTER: JsonSchema = { type: 'object', properties: {} };

/**
 * Create or edit one prompt. The scope is chosen once; a group prompt picks
 * what it consolidates and, over results, the image prompt whose results it
 * reads. Switching auto-run on is the owner's or a manager's (the server
 * refuses it otherwise), so an editor sees it disabled unless already on.
 */
export function PromptForm({
  initial,
  imagePrompts,
  canManage,
  busy,
  onSubmit,
  onCancel,
}: {
  initial?: Prompt;
  imagePrompts: Prompt[];
  canManage: boolean;
  busy: boolean;
  onSubmit: (fields: PromptFields) => void;
  onCancel: () => void;
}) {
  const { t } = useT();
  const [name, setName] = useState(initial?.name ?? '');
  const [scope, setScope] = useState<PromptScope>(initial?.scope ?? 'image');
  const [instruction, setInstruction] = useState(initial?.instruction ?? '');
  const [structured, setStructured] = useState(initial ? initial.output_schema !== null : true);
  const [schema, setSchema] = useState<JsonSchema | null>(initial?.output_schema ?? STARTER);
  const [inputs, setInputs] = useState<PromptInputs>(initial?.inputs ?? 'images');
  const [member, setMember] = useState(initial?.member_prompt_id ?? '');
  const [autoRun, setAutoRun] = useState(initial?.auto_run ?? false);
  const group = scope === 'group';
  const needsMember = group && inputs !== 'images';
  const valid =
    name.trim() !== '' &&
    instruction.trim() !== '' &&
    (!structured || schema !== null) &&
    (!needsMember || member !== '');

  const submit = () => {
    if (!valid) return;
    onSubmit({
      name: name.trim(),
      scope,
      instruction: instruction.trim(),
      output_schema: structured ? schema : null,
      inputs: group ? inputs : null,
      member_prompt_id: needsMember ? member : null,
      auto_run: group ? false : autoRun,
    });
  };

  return (
    <form
      className="space-y-4"
      data-testid="images-prompt-form"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <div className="grid gap-2">
        <Label htmlFor="images-prompt-name">{t(keys.images.prompts.name)}</Label>
        <Input id="images-prompt-name" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="grid gap-2">
        <Label htmlFor="images-prompt-scope">{t(keys.images.prompts.scope.label)}</Label>
        <NativeSelect
          id="images-prompt-scope"
          value={scope}
          disabled={initial !== undefined}
          onChange={(e) => setScope(e.target.value as PromptScope)}
        >
          {(Object.keys(SCOPE) as PromptScope[]).map((s) => (
            <option key={s} value={s}>
              {t(SCOPE[s])}
            </option>
          ))}
        </NativeSelect>
      </div>
      {group && (
        <div className="grid gap-2">
          <Label htmlFor="images-prompt-inputs">{t(keys.images.prompts.inputs.label)}</Label>
          <NativeSelect
            id="images-prompt-inputs"
            value={inputs}
            onChange={(e) => setInputs(e.target.value as PromptInputs)}
          >
            {(Object.keys(INPUTS) as PromptInputs[]).map((i) => (
              <option key={i} value={i}>
                {t(INPUTS[i])}
              </option>
            ))}
          </NativeSelect>
        </div>
      )}
      {needsMember && (
        <div className="grid gap-2">
          <Label htmlFor="images-prompt-member">{t(keys.images.prompts.member.label)}</Label>
          <NativeSelect
            id="images-prompt-member"
            value={member}
            onChange={(e) => setMember(e.target.value)}
          >
            <option value="">{t(keys.images.prompts.member.none)}</option>
            {imagePrompts.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </NativeSelect>
        </div>
      )}
      <div className="grid gap-2">
        <Label htmlFor="images-prompt-instruction">{t(keys.images.prompts.instruction)}</Label>
        <Textarea
          id="images-prompt-instruction"
          rows={5}
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
        />
      </div>
      <div className="grid gap-2">
        <Label htmlFor="images-prompt-output">{t(keys.images.prompts.output.label)}</Label>
        <NativeSelect
          id="images-prompt-output"
          value={structured ? 'structured' : 'text'}
          onChange={(e) => setStructured(e.target.value === 'structured')}
        >
          <option value="text">{t(keys.images.prompts.output.text)}</option>
          <option value="structured">{t(keys.images.prompts.output.structured)}</option>
        </NativeSelect>
        {/* Kept mounted while the answer is free text, so the draft - even
            JSON that does not parse yet - is still there on the way back. */}
        <div hidden={!structured}>
          <SchemaEditor
            initial={initial?.output_schema ?? STARTER}
            onChange={(draft) => setSchema(draft.schema)}
          />
        </div>
      </div>
      {!group && (
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            data-testid="images-prompt-auto-run"
            checked={autoRun}
            disabled={!canManage && !autoRun}
            onChange={(e) => setAutoRun(e.target.checked)}
          />
          {t(keys.images.prompts.auto_run)}
          {!canManage && (
            <span className="text-muted-foreground">{t(keys.images.prompts.auto_run_manager)}</span>
          )}
        </label>
      )}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel}>
          {t(keys.images.prompts.cancel)}
        </Button>
        <Button type="submit" disabled={busy || !valid} data-testid="images-prompt-submit">
          {t(initial ? keys.images.prompts.save : keys.images.prompts.create)}
        </Button>
      </div>
    </form>
  );
}
