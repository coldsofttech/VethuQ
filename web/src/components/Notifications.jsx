import {
  Toast,
  ToastBody,
  ToastTitle,
  Toaster,
  useToastController,
} from '@fluentui/react-components';
import { createContext, useCallback, useContext, useMemo } from 'react';

const TOASTER = 'app-toasts';
const NotifyContext = createContext(() => {});

/**
 * Toasts in the bottom right corner, above the status bar. `notify({ title, body, intent })` shows
 * one; `intent` is 'success' (the default), 'info', 'warning' or 'error', and an error stays
 * longer.
 */
export function NotifyProvider({ children }) {
  const { dispatchToast } = useToastController(TOASTER);

  const notify = useCallback(
    ({ title, body, intent = 'success' }) =>
      dispatchToast(
        <Toast>
          <ToastTitle>{title}</ToastTitle>
          {body && <ToastBody>{body}</ToastBody>}
        </Toast>,
        { intent, timeout: intent === 'error' ? 10000 : 5000 },
      ),
    [dispatchToast],
  );

  const value = useMemo(() => notify, [notify]);
  return (
    <NotifyContext.Provider value={value}>
      {children}
      <Toaster toasterId={TOASTER} position="bottom-end" offset={{ vertical: 36, horizontal: 8 }} />
    </NotifyContext.Provider>
  );
}

export function useNotify() {
  return useContext(NotifyContext);
}
