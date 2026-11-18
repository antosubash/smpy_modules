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

export function RichText({ nodes }: { nodes: Node[] }) {
  return <div className="space-y-3">{nodes.map(render)}</div>;
}
