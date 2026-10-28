/**
 * The public surface of `@simple-module-py/images`: what a plugin's
 * `images-steps.ts` imports. No page or React-tree import belongs here - a
 * plugin must be able to load this without pulling in the console.
 */
export type {
  ResultKind,
  ResultViewProps,
  ResultViewRegistration,
} from './components/results/registry';
export { registerResultView } from './components/results/registry';
