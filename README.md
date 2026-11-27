<h1 align="center"><img src="docs/logo-dark.svg" alt="Turtlemap: dependencies all the way down" width="560"></h1>

Turtlemap shows a Python, JavaScript or TypeScript codebase as pictures
instead of text. It was built to make code easier to follow for people with
dyslexia, but it works for anyone who wants a map of unfamiliar code.

It runs on your machine and never sends your code anywhere.

## Quick start

```bash
poetry install --with dev
poetry run turtlemap path/to/project
```

This opens Turtlemap in your browser. Leave out the folder to pick a project,
or a recent one, on the start screen. To try it on itself, run
`poetry run turtlemap .` from this repository.

| Option | What it does |
|---|---|
| `folder` | The project to open |
| `--diff RANGE` | Highlight what changed in a git range ([see below](#comparing-git-revisions)) |
| `--port N` | Use a fixed port instead of a free one |
| `--host ADDRESS` | Listen on another address; `0.0.0.0` lets your phone or another computer on the same network open it, and prints the address to use. Anyone on that network with the link can read the code |
| `--no-open` | Print the address instead of opening your browser |
| `--no-watch` | Don't redraw the map when source files change |
| `--no-update` | Don't update Turtlemap itself ([see below](#staying-up-to-date)) |

## Two views

### The map

A package diagram: folders as nested frames, modules as boxes, and the
dependencies between modules as ribbons. Click a folder's heading to fold it
into one box, and click a folded folder to open it again. Click the **▸** on a
module to open it into its classes and functions, and on a class to show its
methods; ribbons then attach to whatever is showing. Large projects start with
their side folders (such as `tests/`) and deepest folders folded. Folding and
opening in the **Files** and **Changes** trees does the same to the map.

- **Each folder is laid out on its own.** Its modules and subfolders sit in
  columns by how they depend on each other, so opening or folding a box only
  makes it bigger or smaller; everything around it keeps its column and its
  order. Boxes that depend on nothing else in the folder spread over several
  columns instead of one tall one.
- **Ribbons flow left to right**, from the module that depends to the one it
  depends on, and leave or enter a folder through its right or left side.
- **A ribbon's width** shows how many dependencies it stands for, counted
  between the classes and functions inside each module: inherits, has a field
  of, creates, calls, reads, writes and uses. **⚲ Filter** picks which kinds
  count.
- **Every ribbon into one module merges into one trunk**, coloured for that
  module. Hues follow the folder tree, so modules in the same folder get
  neighbouring colours.
- **Long ribbons run in lanes** between the boxes they skip. Ribbons that
  are not part of the same trunk keep a gap between them.
- **A real cycle** is drawn as a thin grey line looping back.
- **Hover** over a module or folder to light up its ribbons; the rest fade.
  **Click** a module to keep them lit and to read its code in the panel
  below. Click the background to let go.
- **Hover over a ribbon** to see the dependencies it is made of. Click it to
  zoom to both ends.
- **Open a module from the left panel** to show only the modules it uses or
  is used by. **✕ Show all** brings the rest back.
- **Libraries** share one box. Click it to open it into one box per library.

The code panel under the map shows the code of the module you clicked, folded
to its classes and functions.

### Filters

Press **⚲ Filter** to choose which kinds of box and line the map shows.

- **Presets** set both at once:

  | Preset | Boxes | Lines |
  |---|---|---|
  | Everything | all of them | all of them |
  | Data | data classes, enums and their fields | has a field of, inherits, implements |
  | Inheritance | classes, interfaces and type parameters | inherits, implements, stands for |
  | Execution | functions, methods and the classes that hold them, libraries | calls, creates |

- **Tick or untick** any kind of box or line, and the preset becomes
  *Custom*. **↺** goes back to the preset you started from. Hover over a line
  kind and press **only** to show just that kind.
- **Click a line in the Key** to show or hide that kind too.
- **Hidden boxes** are removed, and packages and modules shrink to what is
  left. Choose **fade** to keep them in place, greyed out.
- **Keep boxes a shown line touches** keeps a hidden box, faded, when a line
  you show starts or ends there, so no line ends in nothing.
- **Tests** hides test files and the libraries only they use.
- **Has a field of** lines end in a mark for how many the field holds:

  | End | Means |
  |---|---|
  | Two bars | exactly one |
  | Circle and bar | zero or one (`Optional`) |
  | Crow's foot | many (a list, set, tuple or dict) |

- Classes that only show fields open by themselves.
- The chip in the corner says which filter is on. **✕** goes back to
  Everything.
- Finding a box the filter hides shows it anyway, until you change the filter.
- Each project remembers its own filter.

### The blueprint

Click a function to see it as a dataflow graph, in the style of Unreal Engine
blueprints.

- **Each value is a wire**, coloured by its type.
- **A white line** marks where the order of steps matters.
- **⧉ on a call** unfolds the called function in place. **Go into** makes it
  the whole view.
- **Hover over a wire** to see both ends and its full type. **Click it** to
  zoom out until both ends fit on screen.
- **Nodes read like the code.** A node has no title: its body is its code,
  laid out one part per row, such as `len(`, the argument, then `)`. Each
  input sits on the left edge, labelled with the value it reads or its
  literal. Each output sits on the right edge, written `→ name` when it is
  assigned. Every operator and call is a node of its own.
- **Steps that must run in order** have a coloured bar along the top carrying
  their white execution pins. Pure nodes have no bar, only a coloured left
  edge.
- **Nested functions and lambdas** are frames drawn around their own body.
- **Loops** are frames too, like a callback: items come in on the header, each
  item and the start ▶ come out of the strip below it, and **then** carries on
  once the loop is done.
- **Comprehensions and generator expressions** are pure loop frames, with no ▶.
  Items come in on the header and each element comes out of the strip. The body
  wires back into a band on the frame's right edge (`item`, `yield`, or `key`
  and `value`, plus a `keep if` for each `if`), and the finished list, set,
  dict or generator leaves from the header's right. Each further `for` is a
  frame inside the one before, and its own result wires into the outer band's
  `yield from` pin.
- **An `if`, `match` or `switch`** is a frame of stacked lanes, one per arm,
  each headed by its condition. A lane starts at the ▶ on its top-left, and
  **then** carries on after the branch. Only `a if c else b` becomes a Select.
- **Variables whose value crosses a frame** are one node, placed where they are
  first set (or *unset* just before the branch or loop that sets them). Faint
  dotted wires run from it to each Get, Set, `+=` or `.append` that uses it.
- **Zoom into a lane or loop** and a breadcrumb in the corner lists the frames
  you are in and their conditions.

The code panel highlights the line behind whichever node you select. It works
the other way too: click a line of code to select its node and glide the
blueprint to it. When several nodes share a line, click again to step through
them.

### Getting around

- Press `/` to find any file, class or function.
- Click a folder, file, class or function in the left panel to go to it.
  The ▸ arrow beside a folder opens or folds it, in the panel and on the map
  together: both trees always show the same folders open.
- When you hover over something, lines that lead off screen get a marker on
  the edge of the view. Click a marker to glide there.
- The **Code** tab hides, shows or resizes the code panel.

## Reading settings

The cog menu changes the label font (Lexend, Atkinson Hyperlegible, Comic
Neue or monospace), the text size, the background, and whether names are
spaced out.

Both views are laid out without randomness, so the same code always looks
the same.

## Privacy

- Turtlemap reads your code but never imports or runs it.
- The server listens only on `127.0.0.1` and needs a token made at launch.
- The browser's only outbound request is for web fonts from Google Fonts.
  Offline, it uses system fonts.
- The server's only outbound request is a `git fetch` of Turtlemap's own `main`
  every five minutes ([see below](#staying-up-to-date)). `--no-update` turns it
  off.

## Staying up to date

When Turtlemap runs from a git checkout of itself on `main`, it fetches `main`
every five minutes and updates itself:

| What changed on `main` | What happens |
|---|---|
| The browser app | It pulls, and open pages offer **Refresh** |
| The server code | It pulls and starts again on the same address, with the same project open, then pages offer **Refresh** |
| `pyproject.toml` or `poetry.lock` | It doesn't pull. Pages say to run `git pull` and `poetry install`, then start Turtlemap again |

It only ever fast-forwards. It leaves the checkout alone when it is on another
branch, has uncommitted changes to tracked files, or has commits that are not
on `main`.

## Large projects

The first time you open a large project it takes a while to read. A monorepo of
about 2,700 modules takes around 15 seconds.

The map is built one file at a time and cached in `~/.cache/turtlemap`. Each
file's piece remembers what it read while it was built: the other files, by a
hash of their contents, and the answers it got when it looked a module up. When
something changes, only the pieces whose inputs changed are rebuilt. Saving a
file without changing it rebuilds nothing.

Pieces are shared between your working copy and the revisions you compare it
with. Each file keeps its last few pieces, and any revision where a piece's
inputs are the same reuses it. Opening a comparison builds only the files the
branch changed and the files that use them, and going back to the project
doesn't read it again.

While Turtlemap is open it watches the project. When you save a source file or a
`tsconfig.json`, it rebuilds what that file reaches and redraws the map in
place, keeping where you were looking, what you had open and what you had
selected. The browser fetches only the files that were rebuilt, not the whole
map, and keeps the blueprints and code it already has for every other file. An
edit to a file few others use shows up quickly. An edit to a module that hundreds
of others import takes a few seconds, because each of them is rebuilt.
**↻ Reload** does the same check on demand. Blueprints are built when you open
them.

The watcher skips the folders Turtlemap never reads, such as `node_modules` and
hidden folders, so a large `node_modules` does not use up Linux's inotify
watches. If the watcher cannot start, Turtlemap carries on without it and
**↻ Reload** still works.

## Comparing git revisions

Press **± Compare** and type a git range, or start with one:

```bash
poetry run turtlemap path/to/project --diff develop...my-branch
```

| Range | Compares |
|---|---|
| `A..B` | the tips of A and B |
| `A...B` | B with where it branched off A, like a pull request |
| `A` | A with your working copy, including uncommitted files |

Everything shows the newer side. Things that were removed are added back so
you can see them go. When the newer side is your working copy, the comparison
follows your edits as you save them.

| Colour | Badge | Meaning |
|---|---|---|
| Green | `+` | added |
| Red | `−` | removed |
| Yellow | `~` | changed, or something inside it changed |

The colours appear on the map, the file tree, blueprints and the code. A call
turns yellow when the function it calls changed. The panel under the map lists
every changed file.

The map's ribbons take the same colours, and every unchanged ribbon turns
grey: a dependency the change added, one it removed, or one whose kind
changed. A ribbon that stands for several dependencies turns yellow when only
some of them changed. Hover over it to see which ones. Lines are compared for
the files that changed.

### Ticking off what you have reviewed

While comparing, the left panel has a **Changes** tab that lists only the
changed files, like a pull request.

- Each file opens into the parts that changed: functions, methods, class
  bodies and module-level code. Opening a file or class here shows it on the
  map too.
- Tick a part, file or folder to mark it seen. The ✓ **Seen** box does the
  same for what you are looking at.
- If a part changes again later, only that part is unticked.

Seen marks are saved in `~/.config/turtlemap/seen`.

## Comments

Select something and press **C** to comment on it:

- **On the map**, click a box. ⌘/Ctrl-click adds more, and Shift-drag selects
  a group.
- **In a blueprint**, the same with nodes.
- **In the code panel**, drag down the line numbers.

Comments show as 💬 pins. The **Comments** tab lists them, and `[` and `]` step
through the open ones.

- Only you can resolve a comment.
- A line comment follows its code when lines move, and is marked *outdated*
  when that code changes.
- Comments are saved in `~/.config/turtlemap/comments`.

### Working with a coding agent

An agent working on the same branch can read and answer your comments. It can
reply and mark a comment seen, working or done, but it cannot resolve it. You
see its replies and status live.

`turtlemap-agent` is the command-line way in. Run it through Poetry from this
repository; an alias saves typing:

```bash
alias turtlemap-agent='poetry -C /path/to/this/repo run turtlemap-agent --root "$PWD"'
```

```bash
turtlemap-agent watch            # one line per new comment, reply or resolve
turtlemap-agent show c3          # the thread and the code it points at
turtlemap-agent working c3 --note "updating plots.py"
turtlemap-agent reply c3 "Split it into two functions"
turtlemap-agent done c3
turtlemap-agent status "running the tests"
```

In Claude Code, run `turtlemap-agent watch --once` as a background command. It
exits when there are new comments, which wakes the agent. Start it again after
handling them.

`turtlemap-mcp` offers the same tools over MCP:

```bash
claude mcp add turtlemap -- poetry -C /path/to/this/repo run turtlemap-mcp --root /path/to/project
```

While Turtlemap runs, it saves its address and a separate agent token in
`~/.config/turtlemap/servers`, readable only by you.

### Asking about the structure

The agent can also ask about the code:

```bash
turtlemap-agent query report                 # every module, the most coupled pairs, what is too large
turtlemap-agent query describe pkg/plots.py  # what it contains, its size, its links
turtlemap-agent query cohesion Plotter        # a class, module, package or function
turtlemap-agent query coupling pkg/a.py pkg/b.py
turtlemap-agent query blueprint Plotter.draw  # a function's nodes and wires as text
turtlemap-agent query tree pkg --depth 3
turtlemap-agent query find plot
```

Names can be paths, dotted modules, `Class.method` or map ids. Every answer
explains how it was worked out:

| Measure | How it is worked out |
|---|---|
| Class cohesion | LCOM4: groups of methods that share no field and don't call each other |
| Module and package cohesion | Linked groups of members, and internal links ÷ all links |
| Function cohesion | Independent dataflow strands (a rough guide) |
| Coupling | Links between two parts, weighted by kind |
| Instability | Ce ÷ (Ca + Ce), leaving tests out of Ca |
| Size | Flags anything too large (see below) |

Size flags:

| Thing | Too large when it has more than |
|---|---|
| Folder | 15 files and folders, or 6,000 lines |
| File | 500 lines, or 40 classes and functions |
| Class | 300 lines, or 20 methods |
| Function | 50 lines, or a complexity of 15 |

Tests are left out of the size checks.

## Languages

| Language | Read with | Files |
|---|---|---|
| Python | `ast` | `.py` |
| JavaScript and TypeScript | tree-sitter | `.js`, `.jsx`, `.mjs`, `.cjs`, `.ts`, `.tsx` |

- `.d.ts` and minified files are skipped.
- Imports resolve through relative paths, `index` files, `export *`, `require`
  and the `paths` in `tsconfig.json`.
- Plain scripts in the same folder see each other's top-level names.
- JSX elements count as calls, so a component links to what it renders.

Functions without names are named after where they appear:

| Code | Name |
|---|---|
| `const save = async () => {…}` | `save` |
| `const onClick = useCallback(() => {…}, [])` | `onClick` |
| `const api = { load() {…} }` | `api.load` |
| `describe("parsing", () => {…})` | `describe(parsing)` |
| `items.forEach((item) => {…})` | `forEach(callback)` |

To add a language, write a front end that parses it into the shared model and
a table of its builtins, operators and type names.

## Development

```bash
poetry run mypy .
poetry run pytest tests
```

To measure how straight the wires are, open a project, paste
[dev/layout-stats.js](dev/layout-stats.js) into the browser console, and
compare the numbers before and after a layout change.

### How it fits together

Each language is parsed into one shared model of the code. Everything after
that (the map, blueprints and queries) works only on the model.

| Part | What it does |
|---|---|
| `languages/` | Front ends that parse each language into the model |
| `analysis/model.py` | The shared model of the code |
| `analysis/workspace/` | Finds source files and resolves names across them |
| `analysis/symbols.py` | Lists each module's classes, fields, functions and constants |
| `analysis/dependencies.py` | Builds the arrows on the map |
| `analysis/blueprint/` | Builds a function's blueprint |
| `analysis/outline.py` | Builds the folded code under the map |
| `analysis/structure.py`, `analysis/metrics/` | Answer the agent's structure questions |
| `analysis/diff/` | Compares two git revisions |
| `projects/` | Opens projects, caches them and remembers what you have seen |
| `review/` | Stores comments and works out where they point |
| `web/` | The local server |
| `static/` | The browser app, as plain JavaScript modules |
| `static/core/graph.js` | The browser's one graph of the project: packages down to fields, with function bodies attached as they load, and edges lifted to whatever is on screen |
| `static/map/` | The package diagram; `hierarchy.js` lays it out folder by folder |
| `static/blueprint/` | The function blueprints; `layout.js` lays them out |
| `updates/` | Updates Turtlemap itself from `main` |
| `app.py` | The `turtlemap` command |
| `agent.py`, `mcp.py` | The `turtlemap-agent` and `turtlemap-mcp` commands |
| `config.py` | Where settings and caches are kept |
