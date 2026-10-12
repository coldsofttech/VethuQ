import { sinceOf } from '../credits/labels.js';

/** The filters shared by both tabs. A blank value means "any". */
export const NO_FILTERS = {
  range: '',
  source: '',
  language: '',
  file_type: '',
  engine: '',
  page_source: '',
  band: '',
  day: '',
};

/** What the API takes for a set of filters. A single day beats the period. */
export function toParams(filters) {
  const { range, day, ...rest } = filters;
  return {
    ...rest,
    since: day || sinceOf(range),
    until: day || undefined,
  };
}

/** Which filter each way of grouping narrows to when a row is picked. */
export const NARROWS = {
  source: 'source',
  language: 'language',
  file_type: 'file_type',
  engine: 'engine',
  page_source: 'page_source',
  band: 'band',
  day: 'day',
};

export const GROUP_LABELS = {
  source: 'Source',
  language: 'Language',
  file_type: 'File type',
  engine: 'Engine',
  page_source: 'How read',
  band: 'Confidence band',
  day: 'Day',
};

export const CHIP_LABELS = {
  engine: 'Engine',
  page_source: 'How read',
  band: 'Band',
  day: 'Day',
};
