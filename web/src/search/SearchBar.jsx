import {
  Button,
  Dropdown,
  Input,
  Option,
  Popover,
  PopoverSurface,
  PopoverTrigger,
  ToggleButton,
  Tooltip,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import {
  History20Regular,
  Keyboard20Regular,
  Options20Regular,
  Search20Regular,
  TextCaseTitle20Regular,
} from '@fluentui/react-icons';
import { Menu, MenuItem, MenuList, MenuPopover, MenuTrigger } from '@fluentui/react-components';
import { EnglishKeyboard } from '@vethuq/keyboard-en';
import { useEffect, useMemo, useRef, useState } from 'react';
import { FilterSelect } from '../components/FilterSelect.jsx';
import { SearchOptions } from './SearchOptions.jsx';
import { useScreenKeyboard } from './useScreenKeyboard.js';

const useStyles = makeStyles({
  root: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalS },
  row: { display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalS, flexWrap: 'wrap' },
  box: { flexGrow: 1, minWidth: '260px' },
  narrow: { minWidth: '150px' },
});

/** A dropdown that picks several ids; none picked means any. */
function Multi({ label, placeholder, options, value, onChange }) {
  const styles = useStyles();
  const names = useMemo(
    () => Object.fromEntries(options.map((o) => [o.value, o.label])),
    [options],
  );
  return (
    <Dropdown
      className={styles.narrow}
      multiselect
      aria-label={label}
      placeholder={placeholder}
      value={value.map((v) => names[v] ?? v).join(', ')}
      selectedOptions={value}
      onOptionSelect={(_, data) => onChange(data.selectedOptions)}
    >
      {options.map((option) => (
        <Option key={option.value} value={option.value} text={option.label}>
          {option.label}
        </Option>
      ))}
    </Dropdown>
  );
}

/**
 * The search box and what narrows or shapes a search: file types, sources, language, engine, case, and
 * the options flyout. Enter or the search button runs it.
 */
export function SearchBar({
  form,
  setForm,
  options,
  sources,
  languages,
  recent,
  busy,
  onSearch,
  onClearRecent,
}) {
  const styles = useStyles();
  const set = (patch) => setForm((current) => ({ ...current, ...patch }));

  const [keyboard, setKeyboard] = useState(false);
  const box = useRef(null);
  const canSearch = !busy && form.query.trim() !== '';
  const press = useScreenKeyboard(
    box,
    form.query,
    (query) => set({ query }),
    () => canSearch && onSearch(),
  );
  useEffect(() => {
    if (keyboard) box.current?.focus();
  }, [keyboard]);

  const engines = [
    { value: '', label: 'Default engine' },
    { value: 'all', label: 'All engines' },
    ...options.engines.map((e) => ({ value: e.id, label: e.label })),
    ...(options.engines.some((e) => e.id === 'semantic')
      ? [{ value: 'hybrid', label: 'Hybrid (meaning + words)' }]
      : []),
  ];
  const types = options.file_types.map((t) => ({ value: t.id, label: t.label }));
  const sourceOptions = sources.map((s) => ({ value: String(s.id), label: s.name }));
  const languageOptions = languages.map((l) => ({ value: l.id, label: l.label }));
  const unavailable = new Set(options.engines.filter((e) => !e.available).map((e) => e.id));

  return (
    <div className={styles.root}>
      <form
        className={styles.row}
        onSubmit={(event) => {
          event.preventDefault();
          onSearch();
        }}
      >
        <Input
          ref={box}
          className={styles.box}
          size="large"
          type="search"
          // The on-screen keyboard is in use: keep the device's own keyboard from opening too.
          inputMode={keyboard ? 'none' : undefined}
          placeholder="Search your documents"
          aria-label="Search text"
          value={form.query}
          onChange={(_, data) => set({ query: data.value })}
          contentAfter={
            <Menu>
              <MenuTrigger disableButtonEnhancement>
                <Tooltip content="Recent searches" relationship="label">
                  <Button
                    appearance="transparent"
                    size="small"
                    icon={<History20Regular />}
                    disabled={recent.length === 0}
                  />
                </Tooltip>
              </MenuTrigger>
              <MenuPopover>
                <MenuList>
                  {recent.map((query) => (
                    <MenuItem key={query} onClick={() => onSearch(query)}>
                      {query}
                    </MenuItem>
                  ))}
                  <MenuItem onClick={onClearRecent}>Clear the list</MenuItem>
                </MenuList>
              </MenuPopover>
            </Menu>
          }
        />
        <Multi
          label="File types"
          placeholder="All file types"
          options={types}
          value={form.fileTypes}
          onChange={(fileTypes) => set({ fileTypes })}
        />
        <Tooltip content="Search" relationship="label">
          <Button
            appearance="primary"
            icon={<Search20Regular />}
            type="submit"
            disabled={!canSearch}
          />
        </Tooltip>
        <Tooltip content="On-screen keyboard" relationship="label">
          <ToggleButton
            aria-label="On-screen keyboard"
            icon={<Keyboard20Regular />}
            checked={keyboard}
            onClick={() => setKeyboard(!keyboard)}
          />
        </Tooltip>
      </form>
      {keyboard && <EnglishKeyboard onKey={press} onClose={() => setKeyboard(false)} />}
      <div className={styles.row}>
        <FilterSelect
          label="Engine"
          value={form.engine}
          options={engines.map((e) =>
            unavailable.has(e.value) ? { ...e, label: `${e.label} (unavailable)` } : e,
          )}
          onChange={(engine) => set({ engine })}
        />
        <Tooltip
          content={form.caseSensitive ? 'Case matters' : 'Case is ignored'}
          relationship="label"
        >
          <ToggleButton
            aria-label="Match case"
            icon={<TextCaseTitle20Regular />}
            checked={form.caseSensitive}
            onClick={() => set({ caseSensitive: !form.caseSensitive })}
          />
        </Tooltip>
        <Multi
          label="Sources"
          placeholder="All sources"
          options={sourceOptions}
          value={form.sources}
          onChange={(selected) => set({ sources: selected })}
        />
        <Multi
          label="Languages"
          placeholder="All languages"
          options={languageOptions}
          value={form.languages}
          onChange={(selected) => set({ languages: selected })}
        />
        <Popover positioning="below-end" trapFocus>
          <PopoverTrigger disableButtonEnhancement>
            <Tooltip content="Search options" relationship="label">
              <Button icon={<Options20Regular />} aria-label="Search options" />
            </Tooltip>
          </PopoverTrigger>
          <PopoverSurface>
            <SearchOptions form={form} setForm={setForm} options={options} />
          </PopoverSurface>
        </Popover>
      </div>
    </div>
  );
}
