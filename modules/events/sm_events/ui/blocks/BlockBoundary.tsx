import { Component, type ReactNode } from 'react';

/** A block must never take the page down: a render that throws leaves an empty fragment, and the
 *  rest of the page stands. (A failed fetch is handled in the block itself; this is for what it
 *  did not foresee.) */
export class BlockBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown) {
    console.warn('[events] a block failed to render:', error);
  }

  render() {
    return this.state.failed ? <></> : this.props.children;
  }
}
