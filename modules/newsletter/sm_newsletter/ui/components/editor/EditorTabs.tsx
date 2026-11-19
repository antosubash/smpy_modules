import { Button } from '@simple-module-py/ui/components/ui/button';

import { keys, useT } from '../../utils/i18n';
import { TestSendDialog } from './TestSendDialog';

const copy = keys.newsletter.preview;

export type EditorTab = 'edit' | 'preview';

/** The class of the pane holding Puck. Off the Edit tab it is taken out of sight and out of the
 *  tab order, but never `display: none`: Puck measures its frame every 100 ms, and a frame in a
 *  `display: none` pane reads as `NaN` wide, which it turns into a `NaN` zoom and a
 *  `top: NaN` on the selected block's action bar (React logs it). Off-screen, at the viewport's own
 *  size, it still has a real width (and the pane carries `inert`). */
export const editPaneClass = (active: boolean): string =>
  active
    ? 'min-h-0 flex-1'
    : 'pointer-events-none invisible fixed -left-[9999px] top-0 h-screen w-screen overflow-hidden';

interface Props {
  tab: EditorTab;
  onTab: (tab: EditorTab) => void;
  campaignId: number;
  canSend: boolean;
  maxRecipients: number;
  flush: () => Promise<boolean>;
  incomplete: boolean;
  /** The host's `public_base_url` is unset: test sends will be refused. */
  baseUrlMissing?: boolean;
}

/** The Edit / Preview switch, and "Send test" for a caller who may send. */
export function EditorTabs(props: Props) {
  const { t } = useT();
  return (
    <>
      {(['edit', 'preview'] as const).map((id) => (
        <Button
          key={id}
          size="sm"
          variant={props.tab === id ? 'default' : 'outline'}
          aria-pressed={props.tab === id}
          onClick={() => props.onTab(id)}
        >
          {t(id === 'edit' ? copy.tab_edit : copy.tab_preview)}
        </Button>
      ))}
      {props.canSend && (
        <TestSendDialog
          campaignId={props.campaignId}
          max={props.maxRecipients}
          beforeSend={props.flush}
          incomplete={props.incomplete}
          baseUrlMissing={props.baseUrlMissing}
        />
      )}
    </>
  );
}
