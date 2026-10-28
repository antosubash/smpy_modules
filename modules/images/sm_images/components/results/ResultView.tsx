import { GenericResultView } from './GenericResultView';
import { getResultView, type ResultViewProps } from './registry';

/** Render one result with the view registered for its `(kind, id)`, else the
 *  generic key/value one. */
export function ResultView(props: ResultViewProps) {
  const Component = getResultView(props.kind, props.id) ?? GenericResultView;
  return <Component {...props} />;
}
