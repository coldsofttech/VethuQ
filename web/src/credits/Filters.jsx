import { Input, makeStyles, tokens } from '@fluentui/react-components';
import { ArrowDownload20Regular, Search20Regular } from '@fluentui/react-icons';
import { useEffect, useState } from 'react';
import { api } from '../api/client.js';
import { download } from '../format.js';
import { Menu, MenuItem, MenuList, MenuPopover, MenuTrigger } from '@fluentui/react-components';
import { ToolButton } from '../components/ToolButton.jsx';
import { FilterSelect } from '../components/FilterSelect.jsx';
import { walletLabel } from './labels.js';

export const useFilterStyles = makeStyles({
  row: { display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: tokens.spacingHorizontalM },
  grow: { flexGrow: 1 },
  page: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM },
  muted: { color: tokens.colorNeutralForeground3 },
  amountOut: { color: tokens.colorPaletteRedForeground1 },
  amountIn: { color: tokens.colorPaletteGreenForeground1 },
});

/** The wallets that can be picked, as options led by "All wallets". */
export function useWalletOptions() {
  const [wallets, setWallets] = useState([]);
  useEffect(() => {
    let live = true;
    api.credits.summary().then(
      (data) => live && setWallets(data.wallets.map((w) => w.wallet)),
      () => {},
    );
    return () => {
      live = false;
    };
  }, []);
  return [
    { value: '', label: 'All wallets' },
    ...wallets.map((w) => ({ value: w, label: walletLabel(w) })),
  ];
}

export function WalletSelect({ value, onChange }) {
  return (
    <FilterSelect label="Wallet" value={value} options={useWalletOptions()} onChange={onChange} />
  );
}

export function SearchBox({ value, onChange, label }) {
  return (
    <Input
      contentBefore={<Search20Regular />}
      placeholder={label}
      aria-label={label}
      value={value}
      onChange={(_, data) => onChange(data.value)}
    />
  );
}

export function ExportMenu({ what, params }) {
  return (
    <Menu>
      <MenuTrigger disableButtonEnhancement>
        <ToolButton label="Export" icon={<ArrowDownload20Regular />} />
      </MenuTrigger>
      <MenuPopover>
        <MenuList>
          <MenuItem onClick={() => download(api.credits.exportUrl(what, 'csv', params))}>
            As CSV
          </MenuItem>
          <MenuItem onClick={() => download(api.credits.exportUrl(what, 'json', params))}>
            As JSON
          </MenuItem>
        </MenuList>
      </MenuPopover>
    </Menu>
  );
}
