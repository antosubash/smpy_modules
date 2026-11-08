/**
 * The RichText toolbar's link button (Puck's menu has none).
 *
 * Asks for an address with `window.prompt`: empty removes the link, an address
 * the server would refuse (`normalizeLink`) is reported and nothing changes.
 */

import { RichTextMenu } from '@puckeditor/core';

import { keys, useT } from '../../../utils/i18n';
import { normalizeLink } from '../../../utils/links';

const copy = keys.newsletter.blocks.rich_text;

/** The few Tiptap editor members this uses. */
interface EditorLike {
  state: { selection: { empty: boolean } };
  isActive(name: string): boolean;
  getAttributes(name: string): Record<string, unknown>;
  chain(): {
    focus(): {
      extendMarkRange(name: string): {
        setLink(attrs: { href: string }): { run(): boolean };
        unsetLink(): { run(): boolean };
      };
    };
  };
}

export function LinkControl({ editor, readOnly }: { editor: unknown; readOnly: boolean }) {
  const { t } = useT();
  const ed = editor as EditorLike | null;

  function toggle() {
    if (!ed) return;
    const current = ed.getAttributes('link').href;
    const answer = window.prompt(
      t(copy.link_prompt),
      typeof current === 'string' ? current : 'https://',
    );
    if (answer === null) return;
    const href = normalizeLink(answer);
    if (href === null) {
      window.alert(t(copy.link_invalid));
      return;
    }
    const chain = ed.chain().focus().extendMarkRange('link');
    if (href === '') chain.unsetLink().run();
    else chain.setLink({ href }).run();
  }

  return (
    <RichTextMenu.Control
      title={t(copy.link_title)}
      icon={
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          aria-hidden="true"
        >
          <path d="M10 13a5 5 0 0 0 7.07 0l3-3a5 5 0 0 0-7.07-7.07l-1 1" />
          <path d="M14 11a5 5 0 0 0-7.07 0l-3 3a5 5 0 0 0 7.07 7.07l1-1" />
        </svg>
      }
      active={ed?.isActive('link') ?? false}
      // Nothing to link: no selected text and the cursor is not in a link.
      disabled={readOnly || !ed || (ed.state.selection.empty && !ed.isActive('link'))}
      onClick={toggle}
    />
  );
}
