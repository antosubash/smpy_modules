/** A plugin's public rendering of an event of its type, beneath the description. It receives
 *  only the type's declared public fields (`public_extra`), the type and the title, and the
 *  page's language; it runs lazily inside a boundary, so a failure shows nothing and the page
 *  around it is unaffected. A type with no registration, or one this server does not have,
 *  renders nothing at all. Console code is never imported here. */

import { useEventExtensions } from '../extensions/load';
import { PluginBoundary } from '../extensions/PluginBoundary';
import { eventType } from '../extensions/registry';

type Props = {
  type: string;
  title: string;
  publicExtra: Readonly<Record<string, unknown>>;
  locale: string;
};

export function PluginDetail({ type, title, publicExtra, locale }: Props) {
  useEventExtensions(); // starts the lazy load; the registry is read after it
  const Detail = eventType(type)?.PublicDetail;
  if (!Detail) return null;
  return (
    <PluginBoundary name={`${type}/public`} fallback={null}>
      <Detail occurrence={null} event={{ type, title }} publicExtra={publicExtra} locale={locale} />
    </PluginBoundary>
  );
}
