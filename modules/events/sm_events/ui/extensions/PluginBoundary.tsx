/** One plugin component, contained: a render error or a failed lazy import shows `fallback`
 *  (the default, or nothing) and is logged once by name; it never reaches the page around it. */
import { Component, type ErrorInfo, type ReactNode, Suspense } from 'react';

type Props = { name: string; fallback: ReactNode; children: ReactNode };
type State = { failed: boolean };

const reported = new Set<string>();

class Boundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, _info: ErrorInfo): void {
    // The class and the plugin's name only: what a plugin throws may hold its data.
    if (reported.has(this.props.name)) return;
    reported.add(this.props.name);
    console.error(`events: the extension ${this.props.name} failed (${error.name})`);
  }

  render(): ReactNode {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

export function PluginBoundary({ name, fallback, children }: Props) {
  return (
    <Boundary name={name} fallback={fallback}>
      <Suspense fallback={fallback}>{children}</Suspense>
    </Boundary>
  );
}

/** Tests only: forget what was logged. */
export const resetReported = () => reported.clear();
