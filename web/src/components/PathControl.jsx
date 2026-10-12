import {
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Input,
  MessageBar,
  MessageBarBody,
  Spinner,
  Text,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { useState } from 'react';
import { api } from '../api/client.js';
import { usePlatform } from '../platform/PlatformProvider.jsx';
import { strings } from '../strings.js';

const text = strings.settings;

const useStyles = makeStyles({
  current: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalXS },
  path: {
    fontFamily: tokens.fontFamilyMonospace,
    wordBreak: 'break-all',
    background: tokens.colorNeutralBackground3,
    padding: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalS}`,
    borderRadius: tokens.borderRadiusMedium,
  },
  actions: { display: 'flex', gap: tokens.spacingHorizontalS, flexWrap: 'wrap' },
  body: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM },
  pick: { display: 'flex', gap: tokens.spacingHorizontalS },
  grow: { flexGrow: 1 },
});

/**
 * The folder a setting points at, with a dialog to change it (or to go back to the default one).
 * The data folder offers to move the existing data along; every change is confirmed in the dialog,
 * which stays open, with a spinner, until the service has finished and shows why if it refuses.
 *
 * @param {{ setting: import('../api/client.js').Setting, busy: boolean, problem: string,
 *   onChange: (value: string, options?: { move: boolean }) => Promise<boolean>,
 *   onReset: (options?: { move: boolean }) => Promise<boolean> }} props
 */
export function PathControl({ setting, busy, problem, onChange, onReset }) {
  const styles = useStyles();
  const { folderDialog } = usePlatform();
  const [mode, setMode] = useState(/** @type {'change' | 'reset' | null} */ (null));
  const [draft, setDraft] = useState('');
  const [move, setMove] = useState(true);
  const locked = Boolean(setting.locked);
  const current = String(setting.value);

  const open = (next) => {
    setDraft(next === 'reset' ? String(setting.default) : current);
    setMove(true);
    setMode(next);
  };

  const confirm = async () => {
    const options = setting.can_move ? { move } : undefined;
    const done = mode === 'reset' ? await onReset(options) : await onChange(draft.trim(), options);
    if (done) setMode(null);
  };

  const browse = async () => {
    try {
      const { path } = await api.dialog.folder(draft || current);
      if (path) setDraft(path);
    } catch {
      // The picker is a convenience; the folder can still be typed.
    }
  };

  const resetting = mode === 'reset';
  const unchanged = !resetting && (draft.trim() === '' || draft.trim() === current);

  return (
    <div className={styles.current}>
      <Text size={200}>{text.pathCurrent}</Text>
      <Text className={styles.path} data-testid={`path-${setting.id}`}>
        {current}
      </Text>
      <div className={styles.actions}>
        <Button disabled={locked || busy} onClick={() => open('change')}>
          {text.change}
        </Button>
        <Button
          appearance="subtle"
          disabled={locked || busy || setting.is_default}
          onClick={() => open('reset')}
        >
          {text.resetFolder}
        </Button>
      </div>

      <Dialog
        open={mode !== null}
        onOpenChange={(_, data) => {
          // Only Escape closes it; the buttons close it themselves, and a stray click must not.
          if (!data.open && data.type === 'escapeKeyDown' && !busy) setMode(null);
        }}
      >
        <DialogSurface>
          <DialogBody>
            <DialogTitle>
              {resetting ? text.resetFolder : `${text.change.replace('…', '')}: ${setting.label}`}
            </DialogTitle>
            <DialogContent className={styles.body}>
              <Text>{setting.description}</Text>
              <div className={styles.pick}>
                <Input
                  className={styles.grow}
                  aria-label={text.folder}
                  placeholder={text.folderPlaceholder}
                  value={draft}
                  disabled={resetting || busy}
                  onChange={(_, data) => setDraft(data.value)}
                />
                {folderDialog && !resetting && (
                  <Button disabled={busy} onClick={browse}>
                    {text.browse}
                  </Button>
                )}
              </div>
              {setting.can_move && (
                <>
                  <Checkbox
                    checked={move}
                    disabled={busy}
                    label={resetting ? text.moveDataReset : text.moveData}
                    onChange={(_, data) => setMove(data.checked === true)}
                  />
                  <Text size={200}>{text.moveWarning}</Text>
                </>
              )}
              {problem && (
                <MessageBar intent="error">
                  <MessageBarBody>{problem}</MessageBarBody>
                </MessageBar>
              )}
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" disabled={busy} onClick={() => setMode(null)}>
                {text.cancel}
              </Button>
              <Button appearance="primary" disabled={busy || unchanged} onClick={confirm}>
                {busy ? <Spinner size="tiny" /> : resetting ? text.resetFolder : text.changeFolder}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}
