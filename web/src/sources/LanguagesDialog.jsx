import {
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  Input,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { useState } from 'react';
import { api } from '../api/client.js';
import { useApi } from '../api/useApi.js';

const useStyles = makeStyles({
  list: { display: 'flex', flexDirection: 'column', maxHeight: '320px', overflowY: 'auto' },
  note: { color: tokens.colorNeutralForeground2 },
});

/**
 * The languages of a source. None picked means the languages of Settings.
 * @param {{ source: import('../api/client.js').SourceRow | null, onSave: (languages: string[]) => void,
 *   onClose: () => void }} props
 */
function LanguagesBody({ source, onSave, onClose }) {
  const styles = useStyles();
  const catalog = useApi(api.catalog);
  const [picked, setPicked] = useState(/** @type {string[]} */ (source?.languages ?? []));
  const [filter, setFilter] = useState('');

  const all = (catalog.data?.languages ?? []).filter((language) => language.available);
  const shown = all.filter((language) =>
    `${language.label} ${language.native_label} ${language.id}`
      .toLowerCase()
      .includes(filter.toLowerCase()),
  );
  const toggle = (id, checked) =>
    setPicked((current) => (checked ? [...current, id] : current.filter((item) => item !== id)));

  return (
    <Dialog open={source !== null} onOpenChange={(_, data) => !data.open && onClose()}>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>Languages of {source?.name}</DialogTitle>
          <DialogContent>
            <Field
              label="Find a language"
              hint="None picked: the languages from Settings are used."
            >
              <Input value={filter} onChange={(_, data) => setFilter(data.value)} />
            </Field>
            <div className={styles.list}>
              {shown.map((language) => (
                <Checkbox
                  key={language.id}
                  label={
                    language.native_label
                      ? `${language.label} (${language.native_label})`
                      : language.label
                  }
                  checked={picked.includes(language.id)}
                  onChange={(_, data) => toggle(language.id, data.checked === true)}
                />
              ))}
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button appearance="primary" onClick={() => onSave(picked)}>
              Save
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

/** Mounted afresh for each source, so the picks start from what the source has. */
export function LanguagesDialog(props) {
  return <LanguagesBody key={props.source?.id ?? 'none'} {...props} />;
}
