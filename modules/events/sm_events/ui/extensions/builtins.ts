/** This module's own entries in the registry: the built-in `subscriptions` source (external
 *  calendars subscribed to by URL). Registered before the plugin glob loads, so a plugin can
 *  never take the id first. */
import { registerSource, source } from './registry';

export function registerBuiltins(): void {
  if (source('subscriptions')) return;
  registerSource({
    id: 'subscriptions',
    // biome-ignore lint/correctness/noComponentHookFactories: a lazy loader, not a component
    Chip: () => import('../components/subscriptions/ExternalChip'),
    // biome-ignore lint/correctness/noComponentHookFactories: a lazy loader, not a component
    Detail: () => import('../components/subscriptions/ExternalDetail'),
    // biome-ignore lint/correctness/noComponentHookFactories: a lazy loader, not a component
    PublicDetail: () => import('../components/subscriptions/ExternalPublicDetail'),
  });
}
