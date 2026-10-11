# vethuq-background

A background service that works through the VethuQ index queue, so indexing goes on without a
terminal. Free.

    pip install vethuq-background            # Linux
    pip install vethuq-background[windows]   # Windows (pywin32)
    vethuq background install                # installs, starts, and starts with the computer
    vethuq background status

Once the service is running for a data folder, `vethuq index run`, `restart` and `reindex` queue their
work for it (add `--one-off` to run one here). Follow the queue with `vethuq index queue list|show|cancel`
and queue work yourself with `vethuq index submit`. Every request runs with the same `index.run(...)` a
person calls, so settings, `index status|pause|resume|stop`, backups and adaptive workers all apply.

| Command | What it does |
|---|---|
| `install` / `uninstall` | Set the service up (never automatic) or remove it |
| `start` / `stop` / `restart` | Control it |
| `pause` / `resume` | Pause the run going now and take no new request |
| `status` | Installed? running? paused? which database? |
| `host [--once]` | Work the queue here, in the terminal |

**Linux:** a `systemd --user` unit, no root. **Windows:** a Windows service (`VethuQBackground`,
pywin32) run as the installing user (asked for their password) or `--system`; creating and controlling it
needs administrator rights, asked for through a UAC prompt. The service serves one data folder, recorded
at install time (`--db` on the `vethuq` command picks it).

`vethuq-background --db FILE [--once]` is what the service runs.
