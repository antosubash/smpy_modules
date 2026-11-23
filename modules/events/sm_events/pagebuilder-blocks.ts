/**
 * Registers the events blocks (`UpcomingEvents`, `EventsCalendar`) into pagebuilder's palette,
 * where pagebuilder is there to have one. Events knows about pagebuilder; pagebuilder knows
 * nothing about events.
 *
 * This file and `ui/blocks/` are the *only* places in this module's frontend allowed to import
 * `@simple-module-py/pagebuilder`, and nothing reachable from `index.ts` may reach them (the
 * console, the public pages and the `Calendar` component all work on a host that never installed
 * it; `ui/blocks/boundary.test.ts` guards both).
 *
 * Deliberately named `pagebuilder-blocks.ts`, as news', images' and records' are: the host
 * eagerly globs every module's `puck-blocks.ts`, so that name would make a host without
 * pagebuilder resolve the static import below and fail to build. Pagebuilder's own
 * `puck-blocks.ts` globs sibling packages' `pagebuilder-blocks.ts` instead, so only a host with
 * pagebuilder imports this file. `@simple-module-py/pagebuilder` is an optional peer.
 *
 * Nothing here statically reaches `Calendar` or FullCalendar: the calendar block registers its
 * render through `lazyBlock`. Each registration is guarded because it runs eagerly at app start,
 * and a throw would take down the bundle's init rather than quietly leave one block out.
 */

import { registerPuckBlocks } from '@simple-module-py/pagebuilder';

import { EventsCalendarBlock } from './ui/blocks/EventsCalendarBlock';
import { UpcomingEventsBlock } from './ui/blocks/UpcomingEventsBlock';
import { keys } from './ui/utils/i18n';

try {
  registerPuckBlocks({
    blocks: { UpcomingEvents: UpcomingEventsBlock },
    // A catalogue key, resolved by pagebuilder's localizeConfig at render.
    category: { key: 'events', title: keys.events.blocks.palette_group },
    // Page-only: a list of events in the site header or footer would repeat on every page.
  });
} catch (error) {
  // Registering twice throws by design (a name already taken); in a hot-reloading dev server
  // that is a re-run of this module, and it must not blank the editor.
  console.warn('[events] UpcomingEvents block not registered:', error);
}

// Its own guard: a clash on one name must not leave the other unregistered.
try {
  registerPuckBlocks({
    blocks: { EventsCalendar: EventsCalendarBlock },
    category: { key: 'events', title: keys.events.blocks.palette_group },
  });
} catch (error) {
  console.warn('[events] EventsCalendar block not registered:', error);
}
