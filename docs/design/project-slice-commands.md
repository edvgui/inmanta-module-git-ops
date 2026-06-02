# Feature Request: `git-ops project slice` command set

## Summary

Extend the `git-ops` CLI with a new command group, `git-ops project slice`, that lets
users manage individual slices of a project from the command line without having to
hand-edit slice files or write throw-away scripts.

The group introduces three sub-commands:

| Command   | Purpose                                                                 |
| --------- | ----------------------------------------------------------------------- |
| `create`  | Scaffold a new source slice file for a given store.                     |
| `list`    | List all slices of a project, optionally filtered by store.             |
| `inspect` | Dump the fully-resolved view of a single slice as JSON.                 |

These commands live alongside the existing project commands (`update`, `sync`,
`prune`) in `inmanta_git_ops/cli.py`, under the existing `@cli.group("project")`.

## Background

A few concepts from the existing codebase are relevant (see
`inmanta_plugins/git_ops/store.py` and `inmanta_plugins/git_ops/slice.py`):

- **Store** (`SliceStore`): a named collection of slices, defined in a project's
  modules and registered in `SLICE_STORE_REGISTRY` on import. Each store has a
  pydantic `schema` (a subclass of `slice.SliceObjectABC`) and a source folder
  (`store._folder`, e.g. `inmanta:///files/fs/`).
- **Source slice**: an unversioned, user-editable file in the store's source folder
  (`<name>.json` / `<name>.yaml`). The file name (without extension/version) is the
  slice name.
- **Active slice**: a versioned, committed snapshot in the active folder
  (`inmanta:///git_ops/active/<store>/<name>@v<version>.json`). A slice may have
  several active versions.
- **Latest / oldest version**: `SliceStore.get_latest_slice(name)` returns the highest
  active version; the set of active versions is available via
  `load_active_slices()[name]`.
- **In sync**: a source slice is "in sync" when its content matches the latest active
  version. `load_source_slices()` reflects this: when the source content equals the
  latest active attributes, the source slice keeps the latest version; otherwise it is
  emitted as `latest.version + 1` (i.e. out of sync, pending a `sync`).
- **`get_one_slice(name)`**: returns the fully-resolved, merged `Slice` (current vs.
  previous, with `operation`/`path` markers, `version`, `slice_store`, `slice_name`).

## Requirements

### 1. `git-ops project slice create`

Scaffold a brand-new **source** slice file and place it in the correct store's source
folder.

- Inputs (each resolvable via CLI argument, environment variable, or interactive
  prompt when missing — following the existing `click` option pattern with
  `envvar=...` / `show_envvar=True`):
  - **store** — name of the target store (must exist in `SLICE_STORE_REGISTRY`).
  - **name** — the slice name; becomes the source file name.
  - **format/extension** — `json` or `yaml` (default `json`, matching the format the
    rest of the tooling writes).
- The created file must contain **all required properties** of the store's schema, with
  **explicit placeholders** wherever the user must still supply a value. Required
  properties are those without a default (the schema's `required` list, e.g. `name` and
  `root` for the `fs` store) plus mandatory nested relations (cardinality_min ≥ 1).
  Placeholders should be obvious and self-describing (e.g. a sentinel string carrying
  the attribute's description) so the file does not silently validate with bogus data.
- The file is written into the store's source folder (`store.source_path`) under
  `<name>.<extension>`, with no version suffix.
- The command should refuse to overwrite an existing source slice with the same name.
- The command should seed placeholders for required property values (the user edits
  the file afterwards), **not** prompt for each required value.

### 2. `git-ops project slice inspect`

Inspect a single slice.

- Inputs: **store** and **name** (CLI arg / env var / prompt, as above).
- Output: the JSON serialization of `SliceStore.get_one_slice(name)` — the
  fully-resolved, merged slice (attributes with `operation`/`path` markers, `version`,
  `slice_store`, `slice_name`).
- A missing slice should surface a clear error (`get_one_slice` raises `LookupError`).

### 3. `git-ops project slice list`

List the slices of the current project.

- **Filter** by store via `--store <name>` (optional; default lists every registered
  store).
- **Output format** configurable via `--format {table,json}` (default `table`), mirroring
  `git-ops module store list`.
- Each slice "row" contains the same details as the inspect command, except for the attributes.
- Rows should cover slices that exist in either the active store or the source folder.
  A slice with no active version yet (never synced) and a slice deleted from source but
  still active are both meaningful states the output should represent sensibly.

## Technical details

1. **Compiler context.** Similarly to other commands (like prune) a
   compile must be running in order to find the available stores and slices.  Each of
   these commands will trigger a special type of compiles, which doesn't emit any
   slice in the model (similarly to prune).  All other logic should be handled in
   a finalizer, which checks for the current compile mode.
2. **Slice view.** list and inspect command should run in "update" mode, except that
   no slice should be emitted in the model.  But the output version and attributes
   should match the same as an update compile.
3. **Placeholder representation.**  Use <REPLACE_THIS> as placeholder for all values,
   regardless of their types.
4. **Reuse of formatting.** `list` should reuse the existing `texttable` + `json.dumps`
   pattern already used by `git-ops module store list` for consistency.

## Out of scope

- Editing/updating existing slice content (covered by hand-editing + `update`/`sync`).
- Deleting slices, pruning, or any active-store mutation (already covered by `prune`).
- Schema migrations.

## Affected files (anticipated)

- `inmanta_git_ops/cli.py` — new `@project.group("slice")` and its three commands.
- `inmanta_plugins/git_ops/store.py` — possibly small helpers if store loading /
  oldest-version lookup needs to be exposed cleanly.
- `tests/test_cli.py` — CLI invocation tests against `docs/example` (the `fs`,
  `simple`, `recursive` stores).
