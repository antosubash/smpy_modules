import type { ComponentConfig } from '@puckeditor/core';
import { createCheckboxField } from '../../fields';
import { EmptyPlaceholder } from './_shared';

export type IframeWidgetProps = {
  src: string;
  title: string;
  height: string;
  sandboxed: boolean;
};

export const IframeWidget: ComponentConfig<IframeWidgetProps> = {
  label: 'Iframe',
  fields: {
    src: { type: 'text', label: 'Source URL' },
    title: { type: 'text', label: 'Title (accessibility)' },
    height: { type: 'text', label: 'Height (e.g. 600px)' },
    sandboxed: createCheckboxField('Sandbox (block popups & navigation)'),
  },
  defaultProps: {
    src: '',
    title: 'Embedded content',
    height: '600px',
    sandboxed: true,
  },
  render: ({ src, title, height, sandboxed }) =>
    src ? (
      <div className="container mx-auto py-6">
        <iframe
          src={src}
          title={title || 'Embedded content'}
          className="w-full rounded-lg border"
          style={{ height }}
          // NOTE: allow-scripts + allow-same-origin lets a SAME-ORIGIN embedded
          // document remove its own sandbox; the protection is meaningful for
          // cross-origin embeds (the primary use). Do not "simplify" this set
          // or the label without revisiting that trade-off.
          sandbox={sandboxed ? 'allow-scripts allow-same-origin allow-forms' : undefined}
        />
      </div>
    ) : (
      <EmptyPlaceholder label="Iframe (no source)" />
    ),
};
