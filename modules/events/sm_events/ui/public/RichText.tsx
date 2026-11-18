import type { ReactNode } from 'react';
import { safeHref } from '../utils/richtext';
import type { Node } from './richtext-types';

/** The description tree as elements. Each allow-listed tag maps to one element; anything else
 *  renders its children and nothing more. No HTML string is ever parsed or injected: text is
 *  React text, so `<script>` in a description is the characters, not an element. */
const TAGS = {
  p: 'p',
  strong: 'strong',
  em: 'em',
  u: 'u',
  s: 's',
  ul: 'ul',
  ol: 'ol',
  li: 'li',
  blockquote: 'blockquote',
  h2: 'h2',
  h3: 'h3',
} as const;
type Tag = keyof typeof TAGS;
const isTag = (name: string): name is Tag => Object.hasOwn(TAGS, name);

function render(node: Node, key: number): ReactNode {
  if (typeof node === 'string') return node;
  const children = node.c.map(render);
  if (node.t === 'br') return <br key={key} />;
  if (node.t === 'a') {
    const href = safeHref(node.href);
    return href ? (
      <a key={key} href={href} rel="nofollow noopener">
        {children}
      </a>
    ) : (
      <span key={key}>{children}</span>
    );
  }
  if (isTag(node.t)) {
    const Element = TAGS[node.t];
    return <Element key={key}>{children}</Element>;
  }
  return <span key={key}>{children}</span>;
}

/** Running text: the host's stylesheet resets lists and headings, so they are styled here, with the
 *  same utilities the editor's box and news' article body use. */
export const PROSE =
  'space-y-3 [&_h2]:text-xl [&_h2]:font-semibold [&_h3]:text-lg [&_h3]:font-semibold ' +
  '[&_ul]:list-disc [&_ul]:pl-6 [&_ol]:list-decimal [&_ol]:pl-6 [&_li]:my-1 ' +
  '[&_ul_ul]:list-[circle] [&_ol_ol]:list-[lower-alpha] [&_a]:underline ' +
  '[&_blockquote]:border-l-4 [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground';

export function RichText({ nodes }: { nodes: Node[] }) {
  return <div className={PROSE}>{nodes.map(render)}</div>;
}
