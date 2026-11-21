/** The plugin slots for `Calendar`: a chip, a detail and toolbar items per surface, built from
 *  the registry. A plugin component is lazy and runs inside a `PluginBoundary`, so one that
 *  throws or fails to load shows the default (or nothing) and never breaks the calendar. A
 *  plugin never receives more than `CalendarSlots` hands every slot: the console's `Detail` is
 *  never used on the public site, where only `PublicDetail` renders. */
import type { ComponentType } from 'react';
import type {
  CalendarSlots,
  DetailProps,
  EventChipProps,
  ToolbarSlotProps,
} from '../calendar/types';
import { PluginBoundary } from './PluginBoundary';
import { eventType, source, toolbarItems } from './registry';
import type { ToolbarSurface } from './types';

function chipOf(surface: ToolbarSurface, props: EventChipProps) {
  const { occurrence } = props;
  // A source's chip wins over its type's; only these two are looked at.
  const Chip = source(occurrence.source)?.Chip ?? eventType(occurrence.type)?.Chip;
  if (!Chip || surface === 'public') return null;
  return { Chip, name: `${occurrence.source}/${occurrence.type}` };
}

function makeChip(surface: ToolbarSurface): ComponentType<EventChipProps> {
  // biome-ignore lint/correctness/noComponentHookFactories: built once per registry version and memoised by the caller
  return function PluginChip(props) {
    const found = chipOf(surface, props);
    const { Default } = props;
    if (!found) return <Default {...props} />;
    const { Chip, name } = found;
    return (
      <PluginBoundary name={name} fallback={<Default {...props} />}>
        <Chip {...props} />
      </PluginBoundary>
    );
  };
}

function makeDetail(
  surface: ToolbarSurface,
  inner?: ComponentType<DetailProps>,
): ComponentType<DetailProps> {
  // biome-ignore lint/correctness/noComponentHookFactories: built once per registry version and memoised by the caller
  return function PluginDetail(props) {
    const { occurrence, Default } = props;
    const base = inner ?? Default;
    const bySource = source(occurrence.source);
    const byType = eventType(occurrence.type);
    if (surface === 'public') {
      const Public = bySource?.PublicDetail ?? byType?.PublicDetail;
      const Base = base as ComponentType<DetailProps>;
      return (
        <>
          <Base {...props} Default={Default} />
          {Public ? (
            <PluginBoundary name={`${occurrence.source}/public`} fallback={null}>
              <Public
                occurrence={occurrence}
                event={null}
                publicExtra={{}}
                locale={occurrence.lang}
              />
            </PluginBoundary>
          ) : null}
        </>
      );
    }
    const Custom = bySource?.Detail ?? byType?.Detail;
    if (!Custom) {
      const Base = base as ComponentType<DetailProps>;
      return <Base {...props} Default={Default} />;
    }
    return (
      <PluginBoundary
        name={`${occurrence.source}/detail`}
        fallback={<Default {...props} Default={Default} />}
      >
        <Custom {...props} />
      </PluginBoundary>
    );
  };
}

function makeToolbar(
  placement: 'start' | 'end',
  surface: ToolbarSurface,
): ComponentType<ToolbarSlotProps> | undefined {
  const items = toolbarItems(placement, surface);
  if (items.length === 0) return undefined;
  // biome-ignore lint/correctness/noComponentHookFactories: built once per registry version and memoised by the caller
  return function PluginToolbar(props) {
    return (
      <>
        {items.map(({ id, Component }) => (
          <PluginBoundary key={id} name={`toolbar:${id}`} fallback={null}>
            <Component {...props} />
          </PluginBoundary>
        ))}
      </>
    );
  };
}

/** The slots for `surface`. Call it after `useEventExtensions()` is true (the registry is then
 *  complete); `inner` is the surface's own detail (the public site's "open the event page" link),
 *  which a plugin's public detail is rendered beneath. */
export function buildSlots(
  surface: ToolbarSurface,
  inner?: ComponentType<DetailProps>,
): CalendarSlots {
  return {
    EventChip: makeChip(surface),
    Detail: makeDetail(surface, inner),
    ToolbarStart: makeToolbar('start', surface),
    ToolbarEnd: makeToolbar('end', surface),
  };
}
