/** Wire shapes of the prompt and preset routes, mirroring `sm_images/schemas/prompt.py`. */

export type PromptScope = 'image' | 'group';
export type PromptInputs = 'images' | 'results' | 'both';
export type PromptRunScope = 'missing' | 'stale' | 'all';
export type JsonSchema = Record<string, unknown>;

export type Prompt = {
  id: string;
  collection_id: string;
  name: string;
  scope: PromptScope;
  instruction: string;
  /** `null` = free text. */
  output_schema: JsonSchema | null;
  inputs: PromptInputs | null;
  member_prompt_id: string | null;
  auto_run: boolean;
  preset_id: string | null;
  preset_prompt_id: string | null;
  revision: number;
};

/** A create body; an update sends the changed ones (never `scope`). */
export type PromptFields = {
  name: string;
  scope?: PromptScope;
  instruction: string;
  output_schema: JsonSchema | null;
  inputs?: PromptInputs | null;
  member_prompt_id?: string | null;
  auto_run: boolean;
};

export type PromptRun = { status: 'accepted'; scope: PromptRunScope; requested: number | null };

export type PresetPrompt = {
  id: string;
  name: string;
  scope: PromptScope;
  inputs: PromptInputs | null;
  member: string | null;
  auto_run: boolean;
};

export type Preset = {
  id: string;
  /** A key in the plugin's own catalogue. */
  label_key: string;
  group_roles: string[];
  filename_patterns: string[];
  prompts: PresetPrompt[];
  has_cross_check: boolean;
};

/** One result row (`GET /prompts/{id}/results`). A `failed` row keeps the
 *  output of the last run that worked: it is the previous result, not this one. */
export type PromptResult = {
  id: number;
  prompt_id: string;
  image_id: string | null;
  group_id: string | null;
  status: string;
  result_text: string | null;
  result_data: Record<string, unknown> | null;
  error: string | null;
  cross_check: Record<string, unknown> | null;
  stale: boolean;
  review_status: string;
};
