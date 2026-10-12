import { Dropdown, Option } from '@fluentui/react-components';

/** A dropdown that picks one of `options` (`{ value, label }`); the first is usually "Any". */
export function FilterSelect({ label, value, options, onChange }) {
  const current = options.find((option) => option.value === value) ?? options[0];
  return (
    <Dropdown
      aria-label={label}
      value={current.label}
      selectedOptions={[current.value]}
      onOptionSelect={(_, data) => onChange(data.optionValue ?? '')}
    >
      {options.map((option) => (
        <Option key={option.value} value={option.value} text={option.label}>
          {option.label}
        </Option>
      ))}
    </Dropdown>
  );
}
