/** User-supplied names rendered inside a sentence or a table cell are wrapped
 *  in `<bdi>`, so a name that carries direction controls (or is simply written
 *  right to left) cannot reorder the text around it. `aria-label`s stay plain
 *  strings: assistive tech does not lay them out. */
import type { ReactNode } from 'react';
import type { Translate } from './i18n';

/** A private-use code point standing in for the name while `t()` fills in the
 *  rest of the sentence; it is never part of any catalogue string. */
const MARK = '';

export const Name = ({ children }: { children: ReactNode }) => <bdi>{children}</bdi>;

/** `t(key, { name })` as nodes, with the name isolated. */
export function withName(t: Translate, key: string, name: string): ReactNode {
  const [before = '', ...rest] = t(key, { name: MARK }).split(MARK);
  return (
    <>
      {before}
      <bdi>{name}</bdi>
      {rest.join(MARK)}
    </>
  );
}
