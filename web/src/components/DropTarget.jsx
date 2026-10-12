import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSourceActions } from '../sources/useSourceActions.js';
import { useNotify } from './Notifications.jsx';

/**
 * Files and folders dropped on the window (the host sends `vethuq:drop` with their paths) become a
 * source. One at a time, like the Add buttons.
 */
export function DropTarget() {
  const notify = useNotify();
  const actions = useSourceActions();
  const navigate = useNavigate();

  useEffect(() => {
    const onDrop = async (event) => {
      const paths = event.detail?.paths ?? [];
      if (paths.length !== 1) {
        notify({ title: 'Drop one file or folder at a time', intent: 'warning' });
        return;
      }
      if (await actions.add(paths[0])) navigate('/sources');
    };
    window.addEventListener('vethuq:drop', onDrop);
    return () => window.removeEventListener('vethuq:drop', onDrop);
  }, [actions, notify, navigate]);

  return null;
}
