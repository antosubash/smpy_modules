import { type CustomField, usePuck } from '@puckeditor/core';

import { MediaPickerButton } from '../media/MediaPicker';
import type { articlePuckConfig } from './articlePuckConfig';

type ArticleConfig = typeof articlePuckConfig;

function BodyImagePicker({ readOnly }: { readOnly?: boolean }) {
  const { selectedItem, getItemById, getSelectorForId, dispatch } = usePuck<ArticleConfig>();
  if (selectedItem?.type !== 'Image') return null;
  const id = selectedItem.props.id;
  return (
    <MediaPickerButton
      enabled
      disabled={readOnly}
      onSelect={(image) => {
        // Resolve again on selection: a dialog must not replace stale block props.
        const current = getItemById(id);
        const selector = getSelectorForId(id);
        if (current?.type !== 'Image' || !selector) return;
        dispatch({
          type: 'replace',
          destinationIndex: selector.index,
          destinationZone: selector.zone,
          data: {
            ...current,
            props: {
              ...current.props,
              url: image.url,
              alt: current.props.alt || image.altText || '',
            },
          },
        });
      }}
    />
  );
}

/** Enrich only the admin Image field; the public render and URL field stay shared. */
export function withMediaPicker(config: ArticleConfig, enabled: boolean): ArticleConfig {
  if (!enabled) return config;
  const block = config.components.Image;
  const fields = block.fields;
  if (!fields) return config;
  const url = fields.url as CustomField<string>;
  return {
    ...config,
    components: {
      ...config.components,
      Image: {
        ...block,
        fields: {
          ...fields,
          url: {
            ...url,
            render: (props) => (
              <div className="space-y-2">
                {url.render(props)}
                <BodyImagePicker readOnly={props.readOnly} />
              </div>
            ),
          },
        },
      },
    },
  };
}
