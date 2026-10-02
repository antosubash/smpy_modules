import { Input } from '@simple-module-py/ui/components/ui/input';
import { useState } from 'react';

import { keys, useT } from '../../utils/i18n';

const INPUT_ID = 'news-article-tags';

interface Props {
  tags: string[];
  disabled?: boolean;
  suggestions: string[];
  onChange: (tags: string[]) => void;
}

const SUGGESTIONS_ID = 'news-article-tag-suggestions';

/** Tag chips with an add field — the design's `canopy × urban × add…`.
 *
 * Committing on Enter *and* on comma, because tags are typed in a rush between
 * paragraphs and a writer who types "canopy, urban" should get two tags rather
 * than one oddly-named one.
 */
export function TagInput({ tags, disabled = false, suggestions, onChange }: Props) {
  const { t } = useT();
  const [draft, setDraft] = useState('');

  const add = (raw: string) => {
    const name = raw.trim().replace(/,$/, '').trim();
    if (!name) return;
    // Case-insensitively already present: the server would fold them together
    // anyway, so accepting it here would show a duplicate chip until the next
    // reload contradicted it.
    if (tags.some((t) => t.toLowerCase() === name.toLowerCase())) {
      setDraft('');
      return;
    }
    onChange([...tags, name]);
    setDraft('');
  };

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {tags.map((tag) => (
        <span
          key={tag}
          data-testid="article-tag"
          className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs"
        >
          {tag}
          <button
            type="button"
            disabled={disabled}
            aria-label={t(keys.news.tag_input.remove, { tag })}
            className="text-muted-foreground hover:text-foreground"
            onClick={() => onChange(tags.filter((t) => t !== tag))}
          >
            ×
          </button>
        </span>
      ))}

      <Input
        id={INPUT_ID}
        aria-label={t(keys.news.tag_input.add_label)}
        placeholder={t(keys.news.tag_input.add_placeholder)}
        list={SUGGESTIONS_ID}
        value={draft}
        disabled={disabled}
        className="h-7 w-28 border-dashed"
        onChange={(e) => {
          const value = e.target.value;
          if (value.endsWith(',')) add(value);
          else setDraft(value);
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            add(draft);
          }
          // Backspace on an empty field removes the last chip, which is what
          // every other tag field does and what fingers expect.
          if (e.key === 'Backspace' && !draft && tags.length > 0) {
            onChange(tags.slice(0, -1));
          }
        }}
        onBlur={() => add(draft)}
      />

      <datalist id={SUGGESTIONS_ID}>
        {suggestions.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>
    </div>
  );
}
