import { makeStyles, tokens } from '@fluentui/react-components';
import { walletLabel } from './labels.js';

const useStyles = makeStyles({
  root: { width: '100%', display: 'block' },
  axis: { fill: tokens.colorNeutralForeground3, fontSize: '11px' },
  grid: { stroke: tokens.colorNeutralStroke2 },
  legend: { display: 'flex', gap: tokens.spacingHorizontalL, flexWrap: 'wrap' },
  key: { display: 'inline-flex', alignItems: 'center', gap: tokens.spacingHorizontalXS },
  swatch: { width: '10px', height: '10px', borderRadius: '2px', display: 'inline-block' },
});

const COLOURS = [
  tokens.colorBrandBackground,
  tokens.colorPaletteMarigoldBackground3,
  tokens.colorPaletteGreenBackground3,
  tokens.colorPalettePurpleBackground2,
];

/**
 * Stacked bars, one per day, with a series for each wallet. Drawn in SVG, so it needs nothing else.
 * @param {{ days: Array<Record<string, number | string>>, series: string[],
 *   onPick?: (day: string) => void }} props
 */
export function BarChart({ days, series, onPick }) {
  const styles = useStyles();
  const width = 720;
  const height = 220;
  const pad = { left: 40, right: 8, top: 8, bottom: 22 };
  const totals = days.map((day) => series.reduce((sum, name) => sum + Number(day[name] || 0), 0));
  const biggest = Math.max(1, ...totals);
  // Round the top of the scale up to 1, 2 or 5 times a power of ten, so the ticks read well.
  const magnitude = 10 ** Math.floor(Math.log10(biggest));
  const top = [1, 2, 5, 10].map((m) => m * magnitude).find((v) => v >= biggest);
  const step = Math.max(1, Math.ceil(days.length / 6));
  const slot = (width - pad.left - pad.right) / Math.max(days.length, 1);
  const barWidth = Math.max(slot * 0.7, 2);
  const y = (value) => pad.top + (height - pad.top - pad.bottom) * (1 - value / top);

  return (
    <div>
      <svg
        className={styles.root}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Credits spent per day"
      >
        {[0, 0.5, 1].map((fraction) => (
          <g key={fraction}>
            <line
              className={styles.grid}
              x1={pad.left}
              x2={width - pad.right}
              y1={y(top * fraction)}
              y2={y(top * fraction)}
            />
            <text
              className={styles.axis}
              x={pad.left - 6}
              y={y(top * fraction) + 4}
              textAnchor="end"
            >
              {Math.round(top * fraction)}
            </text>
          </g>
        ))}
        {days.map((day, index) => {
          let base = 0;
          const x = pad.left + index * slot + (slot - barWidth) / 2;
          return (
            <g
              key={day.day}
              onClick={onPick ? () => onPick(day.day) : undefined}
              style={{ cursor: onPick ? 'pointer' : 'default' }}
            >
              <title>{`${day.day}: ${totals[index]} credits`}</title>
              <rect
                x={pad.left + index * slot}
                y={pad.top}
                width={slot}
                height={height - pad.top - pad.bottom}
                fill="transparent"
              />
              {series.map((name, s) => {
                const value = Number(day[name] || 0);
                const rect = (
                  <rect
                    key={name}
                    x={x}
                    y={y(base + value)}
                    width={barWidth}
                    height={Math.max(y(base) - y(base + value), 0)}
                    fill={COLOURS[s % COLOURS.length]}
                    rx="2"
                  />
                );
                base += value;
                return rect;
              })}
              {index % step === 0 && (
                <text
                  className={styles.axis}
                  x={x + barWidth / 2}
                  y={height - 6}
                  textAnchor="middle"
                >
                  {String(day.day).slice(5)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <div className={styles.legend}>
        {series.map((name, index) => (
          <span key={name} className={styles.key}>
            <span
              className={styles.swatch}
              style={{ background: COLOURS[index % COLOURS.length] }}
            />
            {walletLabel(name)}
          </span>
        ))}
      </div>
    </div>
  );
}
