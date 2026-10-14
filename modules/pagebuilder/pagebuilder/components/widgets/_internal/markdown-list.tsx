import type { MarkdownListItem } from '../../../utils/markdown';
import { renderRichText } from './rich-text';

// Nested levels switch to hollow bullets, the way browsers mark a second level.
const NESTED_CLASS = 'list-[circle] pl-5 mt-1 space-y-1';

/**
 * A parsed `- ` list, nesting included (#66). The Markdown widget, FAQ answers
 * and widget textareas all render bullets through this, so a nested item can't
 * work in one of them and flatten in another.
 */
export function MarkdownList({
  items,
  className,
}: {
  items: MarkdownListItem[];
  className?: string;
}) {
  return (
    <ul className={className}>
      {items.map((item, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: list items are positional slices of the source text
        <li key={i}>
          {renderRichText(item.text)}
          {item.children.length > 0 && (
            <MarkdownList items={item.children} className={NESTED_CLASS} />
          )}
        </li>
      ))}
    </ul>
  );
}
