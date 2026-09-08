import type { ComponentConfig } from '@puckeditor/core';
import { keys, translate } from '../../utils/i18n';
import { EmptyPlaceholder } from './_shared';

export type HtmlWidgetProps = {
  html: string;
  height: string;
};

export const HtmlWidget: ComponentConfig<HtmlWidgetProps> = {
  label: keys.pagebuilder.blocks.html.label,
  fields: {
    html: {
      type: 'textarea',
      label: keys.pagebuilder.blocks.html.html,
    },
    height: {
      type: 'text',
      label: keys.pagebuilder.blocks.html.height,
    },
  },
  defaultProps: {
    html: '<p>Edit me…</p>',
    height: '400px',
  },
  render: ({ html, height }) =>
    html?.trim() ? (
      <div className="container mx-auto py-6">
        <iframe
          title={translate(keys.pagebuilder.blocks.html.frame_title)}
          className="w-full rounded-lg border bg-white"
          // Stored blocks may omit height (Puck's public Render does not
          // merge defaultProps) — fall back to the default instead of
          // letting the iframe collapse to the UA default ~150px.
          style={{ height: height || '400px' }}
          sandbox="allow-same-origin"
          srcDoc={html}
        />
      </div>
    ) : (
      <EmptyPlaceholder label={translate(keys.pagebuilder.blocks.html.empty)} />
    ),
};
