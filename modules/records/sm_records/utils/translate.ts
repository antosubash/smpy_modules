/**
 * The translator every helper and sub-component in this module takes as a
 * parameter, typed loosely on purpose. `useT()`'s `t` is overloaded against a
 * generated translation-key union; typing a parameter against it (rather
 * than accepting any translator) either blows up TS with an "excessively
 * deep" instantiation over the template-literal key, or fails to unify with
 * the real `TFunction`'s overload set when called.
 *
 * Not `utils/validation.ts`'s `Translate`: that one is deliberately stricter,
 * and `useRecordForm` bridges the two with a cast.
 */
// biome-ignore lint/suspicious/noExplicitAny: see comment above
export type Translate = (...args: any[]) => string;
