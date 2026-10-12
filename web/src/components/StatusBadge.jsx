import { Badge } from '@fluentui/react-components';
import { statusLabel } from '../format.js';

const COLOURS = {
  // files and sources
  indexed: 'success',
  completed: 'success',
  processing: 'brand',
  in_progress: 'brand',
  running: 'brand',
  pending: 'informative',
  modified: 'warning',
  error: 'danger',
  failed: 'danger',
  unsupported: 'subtle',
  removed: 'subtle',
  stopped: 'warning',
  waiting_credits: 'warning',
  waiting_remote: 'informative',
  queued: 'informative',
  submitted: 'informative',
  cancelled: 'subtle',
  expired: 'warning',
};

/** A status in words, coloured by what it means. */
export function StatusBadge({ status, title }) {
  return (
    <Badge appearance="tint" color={COLOURS[status] ?? 'informative'} title={title}>
      {statusLabel(status)}
    </Badge>
  );
}
