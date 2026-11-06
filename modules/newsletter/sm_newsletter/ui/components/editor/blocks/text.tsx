/**
 * The text blocks: Heading and RichText.
 *
 * Fields and limits match `content/blocks.py` (Task 4). Labels hold catalogue
 * keys, resolved by `localizeConfig`; `defaultProps` are seed content and stay
 * as written.
 */

import { type ComponentConfig, type RichText, RichTextMenu } from '@puckeditor/core';

import { keys } from '../../../utils/i18n';
import { isAllowedLink } from '../../../utils/links';

import { block, FONT } from './email';
import { LinkControl } from './LinkControl';

const copy = keys.newsletter.blocks;

const alignOptions = [
  { label: copy.common.align_left, value: 'left' },
  { label: copy.common.align_center, value: 'center' },
];

export interface HeadingProps {
  text: string;
  level: '1' | '2';
  align: 'left' | 'center';
}

export const HeadingBlock: ComponentConfig<HeadingProps> = {
  label: copy.heading.label,
  fields: {
    // `content/blocks.py`: 1-200 characters, no line breaks.
    text: { type: 'text', label: copy.heading.text },
    level: {
      type: 'select',
      label: copy.heading.level,
      options: [
        { label: copy.heading.level_1, value: '1' },
        { label: copy.heading.level_2, value: '2' },
      ],
    },
    align: { type: 'radio', label: copy.common.align, options: alignOptions },
  },
  defaultProps: { text: 'Heading', level: '2', align: 'left' },
  render: ({ text, level, align }) => {
    const style = {
      margin: 0,
      fontFamily: FONT,
      fontWeight: 700,
      lineHeight: 1.25,
      textAlign: align,
      fontSize: level === '1' ? 28 : 22,
    } as const;
    return (
      <div style={block}>
        {level === '1' ? <h1 style={style}>{text}</h1> : <h2 style={style}>{text}</h2>}
      </div>
    );
  },
};

/** Stored as HTML; the server re-serialises it through its allow-list
 *  (ruling R4), so the editor offers only what survives that. */
export interface RichTextProps {
  html: RichText;
}

export const RichTextBlock: ComponentConfig<RichTextProps> = {
  label: copy.rich_text.label,
  fields: {
    html: {
      type: 'richtext',
      label: copy.rich_text.html,
      // Headings, code, rules and alignment would be flattened to text by the
      // sanitiser; offering them would only make the preview disagree.
      options: {
        heading: false,
        code: false,
        codeBlock: false,
        horizontalRule: false,
        textAlign: false,
        // Only what `content/urls.py` keeps; clicking must not follow a link
        // while editing, and a typed address is not turned into one behind
        // the writer's back.
        link: {
          openOnClick: false,
          autolink: false,
          linkOnPaste: false,
          protocols: ['mailto'],
          isAllowedUri: (url) => isAllowedLink(url),
        },
      },
      // Puck's menu has no link button; add one after its groups.
      renderMenu: ({ children, editor, readOnly }) => (
        <RichTextMenu>
          {children}
          <RichTextMenu.Group>
            <LinkControl editor={editor} readOnly={readOnly} />
          </RichTextMenu.Group>
        </RichTextMenu>
      ),
    },
  },
  defaultProps: { html: '<p>Write your message here.</p>' },
  // Puck hands a richtext prop to `render` already rendered.
  render: ({ html }) => <div style={{ ...block, fontSize: 16, lineHeight: 1.6 }}>{html}</div>,
};
