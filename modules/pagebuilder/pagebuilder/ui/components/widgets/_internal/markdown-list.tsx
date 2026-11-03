import { childList, type MarkdownList as MarkdownListBlock } from '../../../utils/markdown';
import { cn } from '../../../utils/widgetUtils';
import { renderRichText } from './rich-text';

// The list owns its marker so a numbered list can't inherit a caller's
// `list-disc`. Nested bullets switch to hollow ones, the way browsers mark a
// second level; nested numbers stay decimal.
const MARKER = { ul: 'list-disc', ol: 'list-decimal' } as const;
const NESTED_MARKER = { ul: 'list-[circle]', ol: 'list-decimal' } as const;
// The marker position is inherited explicitly: preflight's `list-style: none`
// resets it to `outside`, so under the Markdown widget's `list-inside` list
// the nested markers hung back in line with their parent's.
const NESTED_CLASS = '[list-style-position:inherit] pl-5 mt-1 space-y-1';

/**
 * A parsed `- ` / `1. ` list, nesting included (#66). The Markdown widget, FAQ
 * answers and widget textareas all render lists through this, so a nested
 * item can't work in one of them and flatten in another.
 */
export function MarkdownList({
  list,
  className,
  nested = false,
}: {
  list: MarkdownListBlock;
  className?: string;
  nested?: boolean;
}) {
  const List = list.type;
  return (
    <List
      className={cn((nested ? NESTED_MARKER : MARKER)[list.type], className)}
      start={list.start}
    >
      {list.items.map((item, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: list items are positional slices of the source text
        <li key={i}>
          {renderRichText(item.text)}
          {item.children.length > 0 && (
            <MarkdownList list={childList(item)} className={NESTED_CLASS} nested />
          )}
        </li>
      ))}
    </List>
  );
}
