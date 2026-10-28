import '../../images-steps'; // fills the registry before any result renders

import { useT } from '../../utils/i18n';
import { GenericResultView } from './GenericResultView';
import { getResultView, type ResultViewProps } from './registry';

/** Render one result with the view registered for its `(kind, id)`, else the
 *  generic key/value one. */
export function ResultView(props: Omit<ResultViewProps, 't'>) {
  const { t } = useT();
  const Component = getResultView(props.kind, props.id) ?? GenericResultView;
  return <Component {...props} t={t} />;
}
