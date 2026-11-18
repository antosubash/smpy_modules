/** The render-safe description tree (`content/richtext_tree.py`): text, or an allow-listed
 *  element. */
export type Node = string | { t: string; c: Node[]; href?: string };
