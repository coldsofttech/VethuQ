import {
  Button,
  MessageBar,
  MessageBarActions,
  MessageBarBody,
  MessageBarTitle,
} from '@fluentui/react-components';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client.js';

/**
 * The first-run question about sharing anonymous usage statistics. Never pre-selected: nothing is
 * shared unless "Share" is pressed; "Not now" asks no more. Shown only while the policy allows
 * sharing and the question has not been answered.
 */
export function MetricsPrompt() {
  const [status, setStatus] = useState(null);
  useEffect(() => {
    const controller = new AbortController();
    api.maintenance
      .metrics(controller.signal)
      .then(setStatus)
      .catch(() => {});
    return () => controller.abort();
  }, []);

  if (!status || status.prompted || !status.available) return null;

  const answer = (call) => () =>
    call()
      .then(setStatus)
      .catch(() => setStatus(null));
  return (
    <MessageBar intent="info">
      <MessageBarBody>
        <MessageBarTitle>Help improve reading and search?</MessageBarTitle>
        You can share anonymous usage statistics: counts and timings in buckets, never file names,
        text or what you search for. Turning it on adds {status.bonus_percent}% to your daily
        credits while you do. It is off unless you choose it, and you can see exactly what would be
        sent under <Link to="/maintenance">Maintenance</Link>.
      </MessageBarBody>
      <MessageBarActions>
        <Button appearance="primary" onClick={answer(api.maintenance.metricsOptIn)}>
          Share
        </Button>
        <Button onClick={answer(api.maintenance.metricsDismissPrompt)}>Not now</Button>
      </MessageBarActions>
    </MessageBar>
  );
}
