/**
 * What a field inside Puck needs from the editor page.
 *
 * Puck renders a custom field from the config, which is built outside React
 * and knows nothing about the campaign. The card picker's *Refresh* has to go
 * through `useCampaignEditor` (it flushes the autosave and adopts the new
 * revision), so the page provides it here and the picker reads it.
 */

import { createContext, useContext } from 'react';

export interface EditorActions {
  /** Re-snapshot one card block from its source (`useCampaignEditor().refresh`). */
  refresh(blockId: string): Promise<void>;
}

export const EditorActionsContext = createContext<EditorActions>({
  refresh: async () => {},
});

export function useEditorActions(): EditorActions {
  return useContext(EditorActionsContext);
}
