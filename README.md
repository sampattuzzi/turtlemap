# Code Blueprints

A local web app for reading a Python, JavaScript or TypeScript codebase as
pictures instead of text. It was
built to make code easier to follow for people with dyslexia, but it works for
anyone who wants a map of unfamiliar code.

Open a project folder and you get three views:

- **The map.** Packages, modules, classes, functions and fields are nested
  boxes. Click a box to open it. Lines show how things depend on each other:
  inherits, has a field of, creates, calls, reads, writes and uses. Arrows only
  join neighbours, boxes inside the same parent: two open modules get one
  arrow between them, and inside each you see only the arrows between its own
  classes and functions. An arrow gets thicker the more dependencies it stands
  for, and one-off links are faded. Inside an open box, a faint feeder line
  runs from each item that depends on something outside to the corner where
  the box's arrows leave, and from the corner where arrows arrive to each item
  they reach, so every dependency still has a line without crowding the map.
  Hover over an item to light its whole path: its feeder, the arrow between the
  boxes and the feeders in the other box down to what it uses. Hover over an
  arrow between two open boxes to light the feeders that make it up; when
  either end is closed, a card lists the dependencies it stands for instead
  (where arrows share a path, the card lists each of them). When A already
  reaches C through B, the direct A → C arrow is a shortcut: it is drawn very
  faintly, threaded between the boxes without moving them, and its card names
  the way round through B. Every arrow leaves a box on its right and enters
  on its left. Columns are ordered so that as few dependencies as possible
  point backwards; only a real cycle needs an arrow back to an earlier column,
  and it loops round in its own lane between the boxes. Two boxes that depend
  on each other get two separate strands. Select a
  module (click it, or pick it in the file tree or with Find) and the map hides
  every module that neither depends on it nor is used by it; **✕ Show all**
  brings them back. Libraries appear as one box each, and the standard
  library gets one box of its own. Module constants are boxes too, with lines
  to the code that reads them and from them to whatever their value names
  (a table of handlers links to each handler). **Show** in the corner of the
  map hides test files (and libraries only tests import) or constants. The
  panel under the map shows the real source, folded to match what you have
  opened and coloured with the same palette as the wires: strings are the pink
  of a `str` wire, numbers the green of an `int`.
- **The data model.** **▦ Data** in the top bar shows an entity–relationship
  diagram: only dataclasses, models and enums, with their fields, and a line
  from each field that holds another data class to that class. The ends of each
  line show how many: two bars for exactly one, a circle and a bar for zero or
  one (`Optional`), and a crow's foot for many (a list, set, tuple or dict of
  them); the label spells it out, such as *one to many*. When both classes hold
  each other the line pairs the two fields and can read *many to many*; when
  only one side holds the other, the holder counts as one. Classes that link
  to each other are laid out together and the groups are packed side by side.
  The view opens on the package or module you were looking at on the map;
  change it in the list at the top. Data classes from elsewhere that link in
  are faded. More than 250 data classes at once is too many to draw, so a large
  project asks you to pick a package first.
- **The blueprint.** Click a function or method to see it as a dataflow graph
  in the style of Unreal Engine blueprints. Each value is a wire whose colour
  shows its type. A white execution line marks where the order of steps
  matters. Press ⧉ on a call to unfold the called function in place, or **Go
  into** to make it the whole view. Hover over a wire to light it and the two
  pins it joins; a card names both ends and gives the value's full type
  (where wires overlap, it lists each). The code panel highlights the line
  behind whichever node you select. Arithmetic and logic stay readable: a variable
  set from an expression (`north = np.cos(lat) * np.sin(dec) - …`) is one
  node named after the variable, with the expression written out and one input
  per local it reads. Library maths such as `np.sin` or `len` is folded in;
  calls into your own code and reads from your own classes stay as their own
  nodes. The condition of an `if` or `while` is written into the branch, loop
  or select node in the same way.

When you hover over a box on the map or a node in a blueprint, every line
that leads off screen gets a small marker on the edge of the view, like on a
map: an arrow pointing the way and the name of the thing at the other end,
with its file in front (`agent.py › connect()`) when it lives in another
module. Click a marker to glide there.

The code panel under the map has a **Code** tab on its top edge: click it to
hide or show the panel, or drag it to resize. The cog menu holds the reading
settings, which change the label font (Lexend, Atkinson Hyperlegible, Comic
Neue or monospace), the text size, the background, and whether names are
spaced out. It also picks how blueprints and the map are laid out:

| Layout | What you get |
|---|---|
| Balanced (default) | Sweeps each node toward the middle of its wires |
| Classic | The original sweeps, toward the average of the wires; more of them bend |
| Compact | Network simplex: the least wire travel and the shortest blueprints, but fewer straight wires |
| Straighter | Brandes–Köpf locks chains of wires into straight runs, then simplex packs them |
| Straightest | Brandes–Köpf alone: the most straight wires, in taller blueprints |

On the map, Balanced and Classic are the same: the map's own sweeps, which keep
nodes close together. The other three run on each open box's columns, with wires
meeting at node headers.

Press `/` to find any file, class or function.

Nothing leaves your machine. The app parses your code, with Python's `ast`
module for Python and tree-sitter for JavaScript and TypeScript, and never
imports or runs it. It serves the UI from a server on
`127.0.0.1` that answers only requests carrying a token generated at launch.
The one outbound request is for web fonts from Google Fonts; without a
network connection the UI uses system fonts.

## Running it

```bash
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

To try it on itself, open its own source from the repository root:

```bash
poetry run code-blueprints .
```

The first time you open a large project it takes a while to read; the
a monorepo of about 2,700 modules takes around 15 seconds. The result is
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
blueprint (a call turns yellow when the function it calls changed, and a
field read when one of the fields it reads changed); and lines
in both code views, where removed lines are shown in place. The panel under the
map lists every changed file. Each revision is read from git into
`~/.cache/code-blueprints/trees`, so comparing a large project takes a little
while the first time.

### Ticking off what you have reviewed

While comparing, the left panel has two tabs. **Files** is the whole project;
**Changes** lists only the changed files, like a pull request. Each changed
file opens into the parts that changed: functions, methods, a class's own body
(fields, decorators, class attributes) and the module-level code (imports,
constants). Tick a part, a class, a file or a folder to mark it seen; ticking a
file or folder ticks every part inside it. The ✓ **Seen** box next to the
breadcrumbs does the same for the function or file you are looking at.

What you have seen is saved per project in `~/.config/code-blueprints/seen`,
as a fingerprint of each part's old and new text. If a part's change is
different next time (a new commit, an edit, a different range), only that part
is unticked; everything else stays seen, even if you ticked it by ticking its
whole file. Blank lines don't count as a change.

## Comments

Select something and press **C** (or **💬 Comment** in the bar that appears) to
comment on it:

- **On the map**, click a box, ⌘/Ctrl-click to add more, or Shift-drag a
  rectangle around several.
- **In a blueprint**, the same with nodes.
- **In the code panel**, drag down the line numbers (Shift-click extends).

Comments show as 💬 pins on the boxes, nodes and lines they point at; when the
exact spot is folded away, the pin sits on the nearest visible box or folded
line. The **Comments** tab in the left panel lists them, and `[` / `]` step
through the open ones, moving the view to each. Only you can resolve a comment.
A line comment remembers the text it was made on, so it follows the code when
lines move, and is marked *outdated* when that text changes. Comments are saved
per project in `~/.config/code-blueprints/comments`.

### Working with a coding agent

An agent working on the same branch can read and answer comments. While
`code-blueprints` is running, it publishes its address and a separate agent
token in `~/.config/code-blueprints/servers` (readable only by you). The agent
can reply, and mark comments seen, working (with a short note such as
"updating plots.py") or done, but it cannot resolve them. You see its replies
live, its state on each comment, and its status line in the top bar.

`code-blueprints-agent` is the command-line way in. It lives in this
repository's environment, so from the project folder run it through Poetry,
pointing `--root` at the project (an alias saves typing):

```bash
alias code-blueprints-agent='poetry -C /path/to/code-blueprints run code-blueprints-agent --root "$PWD"'
```

```bash
code-blueprints-agent watch            # one line per new comment, reply, resolve
code-blueprints-agent show c3          # the thread and the code it points at
code-blueprints-agent working c3 --note "updating plots.py"
code-blueprints-agent reply c3 "Split it into two functions"
code-blueprints-agent done c3
code-blueprints-agent status "running the tests"
```

In Claude Code, run `code-blueprints-agent watch --once` as a background Bash
command. It waits as long as it takes, then exits with the comments the agent
has not looked at yet, which wakes the agent. Handle them, mark them working or
done, and start it again; anything that arrived in between is reported straight
away.

`code-blueprints-mcp` offers the same through MCP over stdio, with a
`comments_wait` tool to block until the reviewer says something:

```bash
claude mcp add code-blueprints -- poetry -C /path/to/code-blueprints run code-blueprints-mcp --root /path/to/project
```

### Asking about the structure

The agent can ask about the code the same way the map shows it:

```bash
code-blueprints-agent query report                 # every module, the most coupled pairs and what is too large
code-blueprints-agent query describe pkg/plots.py  # contains, size, depends on, used by
code-blueprints-agent query cohesion Plotter        # class, module, package or function
code-blueprints-agent query coupling pkg/a.py pkg/b.py
code-blueprints-agent query blueprint Plotter.draw  # a function's nodes and wires as text
code-blueprints-agent query tree pkg --depth 3
code-blueprints-agent query find plot
```

Names can be map ids (`cls:pkg/plots.py:Plotter`), paths, dotted modules or
`Class.method`; an ambiguous name lists the candidates. Every answer states its
formula:

- **Class cohesion** is LCOM4, the number of groups of methods that share no
  field and don't call each other. A field that most methods use, such as a
  lock, is reported as a hub, with the count you get without it.
- **Module and package cohesion** is the number of linked groups among the
  members, plus internal links ÷ all links to project code.
- **Function cohesion** counts independent dataflow strands. It is a heuristic.
- **Coupling** weighs the edges between two parts by kind. It is *tight* for
  inheritance, writing the other's fields, a cycle, or a high score.
- **Instability** is Ce ÷ (Ca + Ce), with tests left out of Ca.
- **Size** flags a folder with more than 15 files and folders directly inside
  it or 6000 lines in those files, a file over 500 lines or 40 classes and
  functions, a class over 300 lines or 20 methods, and a function over 50
  lines or a complexity of 15. Complexity is 1 plus the function's branches,
  loops, handlers, cases, conditional expressions and extra `and`/`or`
  operands, including the functions nested inside it. Tests are left out.

Only Python, JavaScript and TypeScript are analysed: the numbers say nothing
about other files.

## Languages

Each language has a front end that parses its files into one neutral model of
declarations (functions, classes, interfaces, enums, imports), statements and
expressions. The map, the blueprints and the structure queries work only on
that model, so a new language needs a front end and a table of its builtins,
operators and type names, nothing more.

- **Python** files are read with `ast`.
- **JavaScript and TypeScript** files (`.js`, `.jsx`, `.mjs`, `.cjs`, `.ts`,
  `.tsx`) are read with tree-sitter; `.d.ts` and minified files are skipped.
  Imports resolve through relative paths, `index` files, `export *` barrels,
  `require` and the `paths` in `tsconfig.json`. Plain scripts with no imports
  or exports, like the ones a page loads with `<script>`, see each other's
  top-level names when they share a folder.

Functions without names get one from where they appear, never from a line
number:

| Code | Name |
|---|---|
| `const save = async () => {…}` | `save` |
| `const onClick = useCallback(() => {…}, [])` | `onClick`, wrapped by `useCallback` |
| `const api = { load() {…} }` | `api.load` |
| `describe("parsing", () => {…})` | `describe(parsing)` |
| `items.forEach((item) => {…})` | `forEach(callback)` |

Two in the same scope with the same name get `2`, `3` and so on. Arrow
functions that are a single expression, like `(x) => x + 1`, stay inline in the
blueprint, the way a Python `lambda` does. Functions defined inside another
function show in its blueprint, not as boxes of their own. JSX elements are
calls, so a component links to the components it renders.

## Tests

```bash
poetry run mypy .
poetry run pytest tests
```

## Measuring the layout

[dev/layout-stats.js](dev/layout-stats.js) measures how straight the wires are.
Open a project in the app, paste the script into the browser console, and it
prints a table for 150 sampled blueprints and for the map opened two and three
levels deep: the share of wires with no vertical travel, the mean vertical
travel per wire, blueprint wire crossings and the total drawing height. Run it
before and after a layout change, on a small project and a large one. It measures
whichever layout the cog menu has selected.

## How it works

| Part | What it does |
|---|---|
| `analysis/model.py` | The neutral code model every language is lowered into: declarations, statements, expressions and type expressions |
| `languages/language.py` | What a language front end provides: parsing into the model, source text, and its builtins, operators and type names |
| `languages/python/` | The Python front end, built on `ast`. `language.py` is the `Language`; `lowering.py` lowers statements, with `expressions.py`, `operators.py`, `displays.py` (literals and comprehensions), `signatures.py` (parameters and annotations), `definitions.py` (functions and classes) and `imports.py`; `profile.py` holds Python's builtins and operators and `type_names.py` its type names |
| `languages/javascript/` | The JavaScript and TypeScript front end, built on tree-sitter. `lowering/` turns the syntax tree into the model, one small component per concern (`statements.py`, `expressions.py`, `bindings.py`, `control.py`, `functions.py`, `classes.py`, `exports.py`, `jsx.py`, …) wired together in `module.py` through the ports in `ports.py`; `links.py` reads imports, exports and `require`; `annotations.py` reads type annotations; `nodes.py` holds helpers for tree-sitter nodes; `profile.py` holds the builtins, operators and type names |
| `languages/aliases.py` | Reads the `paths` aliases in `tsconfig.json` and `jsconfig.json` |
| `languages/registry.py` | The languages in use and which files each one reads |
| `analysis/workspace/` | The project's source files and what they say. `files.py` finds the source files; `index.py` maps module names to files, including `src/` layouts, path aliases and `.js` imports that point at `.ts` sources; `parsed.py` is a parsed module and its symbols; `workspace.py` caches parses and resolves names through imports, re-exports, base classes and globals shared between plain scripts |
| `analysis/types.py` | Turns annotations into pin types and colours, and classifies classes as enum, struct (dataclass, model, …), interface or object |
| `analysis/symbols.py` | Summarises each module: classes, fields (including ones assigned to `self`), methods, functions and constants |
| `analysis/import_summary.py` | Summarises each module's imports for the map |
| `analysis/dependencies.py` | Builds the dependency lines for the map, including field reads, writes and method calls through typed objects, whether held in a variable, a field or the result of a call such as `Thing(...).run()` |
| `analysis/blueprint/` | Builds the dataflow and execution graph for one function. `builder.py` walks the statements; `statements/` handles bindings, control flow, loops, data regions and the entry node; `evaluation/` turns expressions into nodes (calls, attributes, operations, constructions) and `folding.py` there decides which expressions fold into one node; `scope.py` tracks what each name holds; `callees.py` works out what a call reaches; `lookups.py` finds pin types; `canvas.py` is the graph being drawn; `printer.py` prints folded expressions |
| `analysis/outline.py` | Builds the folded source outline shown under the map |
| `analysis/project.py` | Ties the analysis together for the server |
| `analysis/structure.py` | Answers structure questions from the map: describe, cohesion, coupling, instability, report, and what is too large |
| `analysis/metrics/` | The measures behind those answers: `code_graph.py` is the tree of packages, modules and members with their edges; `cohesion.py` gathers `class_cohesion.py`, `group_cohesion.py` and `function_cohesion.py`; `coupling.py` scores the links between modules; `size.py` finds folders, files, classes and functions that are too large or complex |
| `analysis/diff/` | Compares two revisions (`revisions.py` names the range and the changed files): `changes.py` marks what changed in each file, `outline.py` and `merge.py` merge the outlines, code and blueprints, `units.py` splits the changes into the parts to review, and `project_diff.py` puts them together |
| `projects/` | Opening projects: `host.py` (`ProjectHost`, the open project and comparison, loaded in the background), `git.py` (ranges, changed files and `git archive`), `comparison.py` (builds a `ProjectDiff` for a range), `overview_cache.py` (caches each project's map on disk), `seen.py` (the changes you have ticked as seen), `recent.py` (recently opened projects) and `registry.py` (publishes a running server's address and agent token) |
| `review/` | Comments: `comments.py` stores threads, the agent's state on each and an event log to wait on; `anchors.py` finds where a comment points now and whether that code changed |
| `agent_tools/` | What `agent.py` and `mcp.py` share: `client.py` finds and calls the running server, `thread_text.py` prints comment threads |
| `web/` | The server: `framework.py` (`Request`, `Response`, the `Router` and the handler that checks tokens, parses bodies and compresses replies), one service per area (`project_service.py`, `comparison_service.py`, `query_service.py`, `collaboration_service.py`), `static_files.py` (serves the page) and `server.py` (puts them on one router) |
| `config.py` | Where settings, comments and the server registry are kept |
| `app.py` | `code-blueprints`: starts the server and opens the browser |
| `agent.py` | `code-blueprints-agent`: watch, answer and query from the command line |
| `mcp.py` | `code-blueprints-mcp`: the same as MCP tools over stdio |
| `static/` | The UI, as plain JavaScript modules. `app.js` starts it. `core/` holds the data and helpers (`data.js`, `project.js`, `dom.js`, `highlight.js`, `settings.js`) and the layered layout (`layout.js`, `simplex.js` for ranks, `columns.js` for ordering); `canvas/` is the pannable view (`viewport.js`, `gestures.js`, `pointers.js`, `scene.js`); `map/` draws the dependency and data maps; `blueprint/` draws a function's blueprint and its code panel; `comments/` holds the comment store, list, cards and marks; `explorer/` is the sidebar, toolbar, palette and the trail of views |
