# Project naming and compatibility

The public product, Python distribution and console command are **Job Hunting**, `job-hunting` and `job-hunting`. The canonical Windows launchers are `Iniciar Job Hunting.cmd` and `Instalar Job Hunting.cmd`. The single neutral icon is `job_hunting.ico`. Visible UI, local laboratory pages, HTTP user-agent names, log filenames and documentation use the final name. Windows taskbar identity is `com.jobhunting.desktop`.

These internal identifiers deliberately remain stable:

- The `autojob` Python package, import paths, `python -m autojob` module entry and `AutoJobError` base class. Renaming them would require a package-wide API migration without changing user-facing behavior.
- The SQLite filename `autojob.sqlite3`, logger namespace `autojob`, existing local-fixture URL paths, `data-autojob-*`/`__autojob*` DOM guards and internal error codes. They are storage/protocol/test contracts, not display names.
- Windows credential references `AutoJob/account/...` and the legacy protected-identity directory under the local application-data folder. Changing them would orphan existing protected data. The vault's display comment/user name use Job Hunting.
- Extension bridge route `/jobmaxxing-wake`, scanner function `scanJobMaxxing`, alarm identifier `jobmaxxing` and the Qt object name `job-maxxing-window`. They preserve compatibility with linked extensions and UI automation. No old-name launcher or duplicate icon is shipped.
- `AUTOJOB_TEST_*` environment flags remain accepted as aliases. Documentation uses `JOB_HUNTING_TEST_*` where applicable.

Only this public source copy was renamed. No original installation, Desktop shortcut, executable or original runtime record was changed.
