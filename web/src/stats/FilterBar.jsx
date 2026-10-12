import {
  InteractionTag,
  InteractionTagPrimary,
  InteractionTagSecondary,
  TagGroup,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { useEffect, useState } from 'react';
import { api } from '../api/client.js';
import { useApi } from '../api/useApi.js';
import { FilterSelect } from '../components/FilterSelect.jsx';
import { RANGES } from '../credits/labels.js';
import { CHIP_LABELS, NO_FILTERS } from './filters.js';

const useStyles = makeStyles({
  root: { display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: tokens.spacingHorizontalM },
});

/** Period, source, language and file type, plus a chip for each narrower choice made in a table. */
export function FilterBar({ filters, onChange }) {
  const styles = useStyles();
  const catalog = useApi(api.catalog);
  const [sources, setSources] = useState([]);

  useEffect(() => {
    let live = true;
    api.sources.list({ removed: true }).then(
      (data) => live && setSources(data.sources),
      () => {},
    );
    return () => {
      live = false;
    };
  }, []);

  const set = (key) => (value) => onChange({ ...filters, [key]: value });
  const sourceOptions = [
    { value: '', label: 'All sources' },
    ...sources.map((s) => ({ value: String(s.id), label: s.name })),
  ];
  const languages = [
    { value: '', label: 'All languages' },
    ...(catalog.data?.languages ?? [])
      .filter((l) => l.available)
      .map((l) => ({ value: l.id, label: l.label })),
  ];
  const types = [
    { value: '', label: 'All file types' },
    ...(catalog.data?.file_types ?? []).map((t) => ({ value: t.id, label: t.label })),
  ];
  // A value picked in a table may not be in a list (a language that is not installed, a removed
  // source): it still shows, as it is.
  const withValue = (options, value) =>
    value && !options.some((o) => o.value === value)
      ? [...options, { value, label: value }]
      : options;
  const chips = Object.keys(CHIP_LABELS).filter((key) => filters[key]);

  return (
    <div className={styles.root}>
      <FilterSelect label="Period" value={filters.range} options={RANGES} onChange={set('range')} />
      <FilterSelect
        label="Source"
        value={filters.source}
        options={withValue(sourceOptions, filters.source)}
        onChange={set('source')}
      />
      <FilterSelect
        label="Language"
        value={filters.language}
        options={withValue(languages, filters.language)}
        onChange={set('language')}
      />
      <FilterSelect
        label="File type"
        value={filters.file_type}
        options={withValue(types, filters.file_type)}
        onChange={set('file_type')}
      />
      {chips.length > 0 && (
        <TagGroup onDismiss={(_, data) => set(data.value)('')} aria-label="Narrowed to">
          {chips.map((key) => (
            <InteractionTag key={key} value={key}>
              <InteractionTagPrimary hasSecondaryAction>
                {CHIP_LABELS[key]}: {filters[key]}
              </InteractionTagPrimary>
              <InteractionTagSecondary aria-label={`Remove ${CHIP_LABELS[key]}`} />
            </InteractionTag>
          ))}
        </TagGroup>
      )}
    </div>
  );
}

export { NO_FILTERS };
