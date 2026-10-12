import {
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
} from '@fluentui/react-components';

/**
 * A table with sortable headers. `columns` are `{ key, label, sortable, render(row), align }`;
 * `sort` is `{ key, order }` and `onSort(key)` toggles it.
 */
export function DataTable({ label, columns, rows, rowKey, sort, onSort, onRowClick, selected }) {
  return (
    <Table aria-label={label} size="small">
      <TableHeader>
        <TableRow>
          {columns.map((column) => (
            <TableHeaderCell
              key={column.key}
              style={column.align === 'end' ? { justifyContent: 'flex-end' } : undefined}
              sortDirection={
                sort?.key === column.key
                  ? sort.order === 'asc'
                    ? 'ascending'
                    : 'descending'
                  : undefined
              }
              onClick={column.sortable && onSort ? () => onSort(column.key) : undefined}
            >
              {column.label}
            </TableHeaderCell>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow
            key={rowKey(row)}
            appearance={selected && selected(row) ? 'brand' : 'none'}
            onClick={onRowClick ? () => onRowClick(row) : undefined}
            style={onRowClick ? { cursor: 'pointer' } : undefined}
          >
            {columns.map((column) => (
              <TableCell
                key={column.key}
                style={column.align === 'end' ? { justifyContent: 'flex-end' } : undefined}
              >
                {column.render ? column.render(row) : row[column.key]}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
