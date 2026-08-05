import type { ComponentConfig } from '@puckeditor/core';
import { EmptyPlaceholder } from './_shared';

export type HtmlWidgetProps = {
  html: string;
  height: string;
};

export const HtmlWidget: ComponentConfig<HtmlWidgetProps> = {
  label: 'Raw HTML',
  fields: {
    html: {
      type: 'textarea',
      label: 'HTML (rendered in sandboxed iframe)',
    },
    height: {
      type: 'text',
      label: 'Height (e.g. 400px)',
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
          title="Embedded HTML"
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
      <EmptyPlaceholder label="Html (no content)" />
    ),
};
