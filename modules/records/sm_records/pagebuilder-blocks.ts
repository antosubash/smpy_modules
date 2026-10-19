/**
 * Registers RecordsList in pagebuilder's palette when pagebuilder is installed.
 * Records knows about pagebuilder; pagebuilder knows nothing about records.
 *
 * Deliberately named `pagebuilder-blocks.ts`: the host eagerly globs every
 * module's `puck-blocks.ts`, so that name would make hosts without pagebuilder
 * resolve the static import below and fail to build. Pagebuilder's own
 * `puck-blocks.ts` globs sibling packages' `pagebuilder-blocks.ts` instead
 * (since 0.0.12), so only hosts with pagebuilder import this file.
 * `@simple-module-py/pagebuilder` is an optional peer dependency.
 */

import { registerPuckBlocks } from '@simple-module-py/pagebuilder/pagebuilder/components/blockRegistry';

import { RecordsListBlock } from './components/widget/RecordsListBlock';
import { keys } from './utils/i18n';

registerPuckBlocks({
  blocks: { RecordsList: RecordsListBlock },
  // A catalogue key, resolved by pagebuilder's localizeConfig at render.
  category: { key: 'data', title: keys.records.widget.palette_group },
  // Page-only: a live records table in the site header or footer would
  // repeat, unfiltered, on every page of the site.
});
