import { Button, Field, Input, Text, makeStyles, tokens } from '@fluentui/react-components';
import { FilterSelect } from '../components/FilterSelect.jsx';
import { EMPTY_FORM } from './form.js';

const useStyles = makeStyles({
  root: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalM,
    width: '340px',
    maxHeight: '70vh',
    overflowY: 'auto',
  },
  muted: { color: tokens.colorNeutralForeground3 },
});

const SORTS = [
  { value: '', label: 'Default' },
  { value: 'path', label: 'By file and page' },
  { value: 'score', label: 'By score' },
  { value: 'rank', label: 'Best match first' },
];

/** The less common choices: what counts as the same character, context, order, and each engine's own settings. */
export function SearchOptions({ form, setForm, options }) {
  const styles = useStyles();
  const set = (patch) => setForm((current) => ({ ...current, ...patch }));
  const engineId = form.engine || options.defaults.engine;
  const engine = options.engines.find((e) => e.id === engineId);
  const hasKeyword = options.engines.filter((e) => e.available && e.id !== 'semantic');

  return (
    <div className={styles.root}>
      <Text weight="semibold">Search options</Text>
      <Field label="Characters around a match" hint={`Default: ${options.defaults.context_chars}`}>
        <Input
          type="number"
          min={0}
          value={form.context}
          onChange={(_, data) => set({ context: data.value })}
        />
      </Field>
      <Field label="Order of results">
        <FilterSelect
          label="Order of results"
          value={form.sort}
          options={SORTS}
          onChange={(sort) => set({ sort })}
        />
      </Field>
      {form.engine === 'hybrid' && (
        <Field label="Keyword engine for Hybrid">
          <FilterSelect
            label="Keyword engine"
            value={form.combine}
            options={[
              { value: '', label: 'Full-text' },
              ...hasKeyword.map((e) => ({ value: e.id, label: e.label })),
            ]}
            onChange={(combine) => set({ combine })}
          />
        </Field>
      )}
      <Text weight="semibold">What counts as the same character</Text>
      {options.normalizers.map((n) => (
        <Field
          key={n.id}
          label={n.id}
          hint={n.setting !== 'auto' ? `Saved: ${n.setting}` : undefined}
        >
          <FilterSelect
            label={`Normalizer ${n.id}`}
            value={form.normalize[n.id] ?? ''}
            options={[
              { value: '', label: 'As saved' },
              ...n.levels.map((l) => ({ value: l, label: l })),
            ]}
            onChange={(level) => set({ normalize: { ...form.normalize, [n.id]: level } })}
          />
        </Field>
      ))}
      {engine && Object.keys(engine.options).length > 0 && (
        <>
          <Text weight="semibold">{engine.label} settings</Text>
          {Object.entries(engine.options).map(([name, fallback]) => (
            <Field key={name} label={name.replace(/_/g, ' ')} hint={`Default: ${fallback}`}>
              <Input
                value={form.options[engine.id]?.[name] ?? ''}
                onChange={(_, data) =>
                  set({
                    options: {
                      ...form.options,
                      [engine.id]: { ...form.options[engine.id], [name]: data.value },
                    },
                  })
                }
              />
            </Field>
          ))}
        </>
      )}
      <Button
        size="small"
        onClick={() =>
          set({
            normalize: EMPTY_FORM.normalize,
            options: EMPTY_FORM.options,
            combine: '',
            sort: '',
            context: '',
          })
        }
      >
        Reset these options
      </Button>
    </div>
  );
}
