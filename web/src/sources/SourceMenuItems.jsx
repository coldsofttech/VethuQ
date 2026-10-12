import { MenuDivider, MenuItem } from '@fluentui/react-components';
import {
  ArrowClockwise20Regular,
  ArrowSync20Regular,
  ArrowUndo20Regular,
  Copy20Regular,
  Delete20Regular,
  FolderOpen20Regular,
  Globe20Regular,
  Play20Regular,
} from '@fluentui/react-icons';
import { api } from '../api/client.js';
import { usePlatform } from '../platform/PlatformProvider.jsx';

/**
 * What can be done with a source, for its row menu and its page. `run(mode)` starts indexing it.
 */
export function SourceMenuItems({
  source,
  run,
  onLanguages,
  onRemove,
  onRestore,
  onPurge,
  onOpen,
}) {
  const platform = usePlatform();
  if (source.removed_at) {
    return (
      <>
        <MenuItem icon={<ArrowUndo20Regular />} onClick={onRestore}>
          Restore
        </MenuItem>
        <MenuItem icon={<Delete20Regular />} onClick={onPurge}>
          Delete for good
        </MenuItem>
      </>
    );
  }
  return (
    <>
      {onOpen && (
        <MenuItem icon={<FolderOpen20Regular />} onClick={onOpen}>
          Open
        </MenuItem>
      )}
      <MenuItem icon={<Play20Regular />} onClick={() => run('run')}>
        Index now
      </MenuItem>
      <MenuItem icon={<ArrowClockwise20Regular />} onClick={() => run('restart')}>
        Retry failed files
      </MenuItem>
      <MenuItem icon={<ArrowSync20Regular />} onClick={() => run('reindex')}>
        Reindex everything
      </MenuItem>
      <MenuItem icon={<Globe20Regular />} onClick={onLanguages}>
        Set languages…
      </MenuItem>
      <MenuDivider />
      <MenuItem
        icon={<Copy20Regular />}
        onClick={() => navigator.clipboard?.writeText(source.path)}
      >
        Copy path
      </MenuItem>
      {platform.reveal && (
        <MenuItem icon={<FolderOpen20Regular />} onClick={() => reveal(source.path)}>
          Show in Explorer
        </MenuItem>
      )}
      <MenuDivider />
      <MenuItem icon={<Delete20Regular />} onClick={onRemove}>
        Remove
      </MenuItem>
    </>
  );
}

function reveal(path) {
  api.os.reveal(path).catch(() => {});
}
