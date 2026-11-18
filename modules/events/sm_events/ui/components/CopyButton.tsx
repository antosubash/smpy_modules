import { Button } from '@simple-module-py/ui/components/ui/button';
import { useState } from 'react';
import { keys, useT } from '../utils/i18n';

/** Copies `text` to the clipboard. Without clipboard access it does nothing and the caller's
 *  field stays selectable: copy by hand. The text is never logged or stored. */
export function CopyButton({ text }: { text: string }) {
  const { t } = useT();
  const [copied, setCopied] = useState(false);
  return (
    <Button
      type="button"
      size="sm"
      variant="outline"
      onClick={async () => {
        try {
          await navigator.clipboard?.writeText(text);
          setCopied(true);
        } catch {
          setCopied(false);
        }
      }}
    >
      {copied ? t(keys.events.common.link_copied) : t(keys.events.common.copy_link)}
    </Button>
  );
}
