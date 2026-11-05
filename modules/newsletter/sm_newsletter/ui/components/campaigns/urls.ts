/** The editor screen for a campaign (`VIEW_PREFIX` in `core/constants.py`). */
export const editorUrl = (id: number): string => `/admin/newsletter/campaigns/${id}`;
/** The campaign list (`MENU_URL` in `core/constants.py`). */
export const campaignsUrl = '/admin/newsletter/';
/** The campaign report screen (`pages/CampaignReport.tsx`). */
export const reportUrl = (id: number): string => `/admin/newsletter/campaigns/${id}/report`;
