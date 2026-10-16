# vethuq-interactive-cli

The interactive shell for `vethuq`: arrow-key menus over the command line.

    pip install vethuq-interactive-cli
    vethuq                    # opens the shell (when installed and run in a terminal)
    vethuq --interactive      # force it
    vethuq-interactive        # the same, as its own command

Use the arrow keys to move, Enter to choose, and Ctrl-C to quit. Every command group is a menu and
every command asks for its parameters (type, choices, defaults, required ones first; optional
options behind one question). The menus are built from the `vethuq` command tree, so the settings
hierarchy (`Settings › Search › fuzzy › threshold`) and the commands installed add-ons add appear
without any code here. Search is guided: query, engine, that engine's options, case, languages.

Errors print in the CLI's `Error: ... / What to do: ...` style and the shell carries on.

## Updates

The shell shows the same `Updates` and `Policy` menus as `vethuq`, and `Update` (the upgrade steps for how VethuQ is installed). It does not print the after-command update notice: that line is for the plain command line. The update check is described in the [`vethuq-cli` README](../cli/README.md#updates-and-notices); it can be switched off with `VETHUQ_UPDATE_CHECK=off`.
