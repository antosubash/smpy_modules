/** The plugin registry: what `events-extensions.ts` files register, looked up by id. Components
 *  arrive as loaders and are wrapped in `React.lazy` once, so a lookup returns the same object
 *  every time (a new one per render would remount the plugin). */
import { type ComponentType, type LazyExoticComponent, lazy } from 'react';
import type { ToolbarSlotProps } from '../calendar/types';
import type {
  EventTypeRegistration,
  LazyComponent,
  SourceRegistration,
  ToolbarItemRegistration,
  ToolbarSurface,
} from './types';

type Lazy<P> = LazyExoticComponent<ComponentType<P>>;
type Wrapped<R> = {
  [K in keyof R]: R[K] extends LazyComponent<infer P> | undefined ? Lazy<P> | undefined : R[K];
};
export type ResolvedType = Wrapped<EventTypeRegistration>;
export type ResolvedSource = Wrapped<SourceRegistration>;
export type ResolvedToolbarItem = Omit<ToolbarItemRegistration, 'Component'> & {
  Component: Lazy<ToolbarSlotProps>;
};

const types = new Map<string, ResolvedType>();
const sources = new Map<string, ResolvedSource>();
const toolbar = new Map<string, ResolvedToolbarItem>();

function wrap<R extends { id: string }>(registration: R): Wrapped<R> {
  const out: Record<string, unknown> = { id: registration.id };
  for (const [name, value] of Object.entries(registration)) {
    if (name !== 'id' && typeof value === 'function')
      out[name] = lazy(value as LazyComponent<unknown>);
    else if (name !== 'id') out[name] = value;
  }
  return out as Wrapped<R>;
}

function put<T>(map: Map<string, T>, kind: string, id: string, value: T): void {
  if (typeof id !== 'string' || id === '')
    throw new Error(`events: a ${kind} needs a non-empty id`);
  if (map.has(id)) throw new Error(`events: ${kind} ${JSON.stringify(id)} is already registered`);
  map.set(id, value);
}

export function registerEventType(registration: EventTypeRegistration): void {
  put(types, 'event type', registration.id, wrap(registration));
}
export function registerSource(registration: SourceRegistration): void {
  put(sources, 'source', registration.id, wrap(registration));
}
export function registerToolbarItem(registration: ToolbarItemRegistration): void {
  put(toolbar, 'toolbar item', registration.id, wrap(registration) as ResolvedToolbarItem);
}

export const eventType = (id: string): ResolvedType | undefined => types.get(id);
export const source = (id: string): ResolvedSource | undefined => sources.get(id);

export function toolbarItems(
  placement: 'start' | 'end',
  surface: ToolbarSurface,
): ResolvedToolbarItem[] {
  return [...toolbar.values()]
    .filter((item) => item.placement === placement && item.surfaces.includes(surface))
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
}

/** Tests only. */
export function clearExtensions(): void {
  types.clear();
  sources.clear();
  toolbar.clear();
}
