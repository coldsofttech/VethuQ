import { Button, Tooltip } from '@fluentui/react-components';
import { forwardRef } from 'react';

/** A toolbar button: just the icon, with its words in a tooltip (and as its accessible name). */
export const ToolButton = forwardRef(function ToolButton({ label, icon, ...props }, ref) {
  return (
    <Tooltip content={label} relationship="label">
      <Button ref={ref} icon={icon} {...props} />
    </Tooltip>
  );
});
