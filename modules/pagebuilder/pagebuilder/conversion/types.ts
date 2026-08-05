/** One entry of a Puck document's `content` array, as stored. */
export type PuckBlock = {
  type: string;
  props: { id: string } & Record<string, unknown>;
};
