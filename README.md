# Code Blueprints

A local web app for reading a Python codebase as pictures instead of text. It was
built to make code easier to follow for people with dyslexia, but it works for
anyone who wants a map of unfamiliar code.

Open a project folder and you get two views:

- **The map.** Packages, modules, classes, functions and fields are nested
  boxes. Click a box to open it. Lines show how things depend on each other:
  inherits, has a field of, creates, calls, reads, writes and uses. Lines are
  coloured only at the deepest level you have opened; the rest stay grey until
  you hover over a box. Libraries appear as one box each, and the standard
  library gets one box of its own. The panel under the map shows the real
  source, folded to match what you have opened.
- **The blueprint.** Click a function or method to see it as a dataflow graph
  in the style of Unreal Engine blueprints. Each value is a wire whose colour
  shows its type. A white execution line marks where the order of steps
  matters. Press ⧉ on a call to unfold the called function in place, or **Go
  into** to make it the whole view. The code panel highlights the line behind
  whichever node you select.

**Aa Reading** changes the label font (Lexend, Atkinson Hyperlegible, Comic
Neue or monospace), the text size, the background, and whether names are
spaced out. Press `/` to find any file, class or function.

Nothing leaves your machine. The app reads your code with Python's `ast`
module and never imports or runs it. It serves the UI from a server on
`127.0.0.1` that answers only requests carrying a token generated at launch.
The one outbound request is for web fonts from Google Fonts; without a
network connection the UI uses system fonts.

## Running it

```bash
cd code_blueprints
poetry install --with dev
poetry run code-blueprints path/to/project
```

This starts a server on `127.0.0.1` and opens the app in your browser. Leave
the folder out to pick one, or a recent project, on the start screen.

| Option | Effect |
|---|---|
| `folder` | Project to open |
| `--diff RANGE` | Tint what changed in a git range (see below) |
| `--port N` | Serve on a fixed port instead of a free one |
| `--no-open` | Print the address instead of opening your browser |

To try it on itself, open its own source:

```bash
poetry run code-blueprints .
```

The first time you open a large project it takes a while to read; the
Adia monorepo, with about 2,700 modules, takes around 15 seconds. The result is
cached in `~/.cache/code-blueprints` and reused until a file changes. Press
**↻ Reload** after editing code. Function blueprints are built on demand when
you open them.

## Comparing git revisions

Press **± Compare** and type a git range, or start with one:

```bash
poetry run code-blueprints path/to/project --diff develop...my-branch
```

| Range | Compares |
|---|---|
| `A..B` | the tips of A and B |
| `A...B` | B with the point where it branched off A, like a pull request |
| `A` | A with your working copy, including uncommitted and untracked files |

The map, blueprints and code show the newer side (B, or your working copy),
and anything that only exists on the older side is added back so you can see
it go. Everything is tinted by what happened to it:

| Tint | Badge | Meaning |
|---|---|---|
| Green | `+` | added |
| Red | `−` | removed |
| Yellow | `~` | changed, or something inside it changed |

This covers packages, modules, classes, functions, methods and fields on the
map; files and symbols in the file tree; nodes, pins and execution wires in a
blueprint (a call turns yellow when the function it calls changed); and lines
in both code views, where removed lines are shown in place. The panel under the
map lists every changed file. Each revision is read from git into
`~/.cache/code-blueprints/trees`, so comparing a large project takes a little
while the first time.

## Tests

```bash
poetry run mypy .
poetry run pytest tests
```

## How it works

| Part | What it does |
|---|---|
| `analysis/workspace.py` | Finds the project's Python files, parses them and resolves imports, including `src/` layouts and relative and re-exported imports |
| `analysis/types.py` | Turns annotations into pin types and colours, and classifies classes as enum, struct (dataclass, model, …), interface or object |
| `analysis/symbols.py` | Summarises each module: classes, fields (including ones assigned to `self`), methods, functions, constants and imports |
| `analysis/dependencies.py` | Builds the dependency lines for the map |
| `analysis/graph.py` | Builds the dataflow and execution graph for one function |
| `analysis/outline.py` | Builds the folded source outline shown under the map |
| `analysis/project.py` | Ties the analysis together for the server |
| `git.py` | Resolves ranges, lists changed files and extracts revisions with `git archive` |
| `analysis/diff.py` | Compares two revisions: symbol changes, merged outlines, code and blueprints |
| `server.py` | Local HTTP API, cached overview, folder opening and recent projects |
| `app.py` | Command line: starts the server and opens the browser |
| `static/` | The UI: layout, wire routing and rendering, in plain JavaScript |
