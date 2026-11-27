---
name: turtlemap-review
description: Prepare a pull request for review in Turtlemap — a readability pass on the diff, then a risk-first tour posted as Turtlemap comments. Use when asked to review, tour or walk the user through a PR or branch in Turtlemap.
---

# Turtlemap review

The user reviews the change in Turtlemap. Your job is to hand them a diff that already reads well, and a tour that walks them through it, riskiest first. Run Turtlemap's commands through Poetry from the Turtlemap repository:

```bash
alias turtlemap-agent='poetry -C /path/to/turtlemap run turtlemap-agent --root "$PWD"'
```

## 1. Serve the diff

From the project's checkout of the branch:

```bash
poetry -C /path/to/turtlemap run turtlemap "$PWD" --diff <base>...HEAD --no-open
```

`<base>` is the branch the PR merges into. Give the user the printed address. Start `turtlemap-agent watch --once` as a background command, and start it again each time it exits.

## 2. Readability pass

Before the user sees the code, make the changed code readable by these rules. Fix what breaks them.

1. **Names explain.** A function, variable, class or module name says what it does, so a reader doesn't need to open it. Long names are fine.
2. **Functions tell a story.** Reading a function tells you what it does, without comments. Keep each function short, and keep all its steps at the same level of detail.
3. **High cohesion, loose coupling.** Each module or class does one job and depends on as few others as possible. No circular dependencies. Higher layers depend on lower layers, never the other way. Check with the project's coupling tools (for example `npx madge --circular --extensions ts,tsx src`) and with Turtlemap's own measures:

   ```bash
   turtlemap-agent query report
   turtlemap-agent query cohesion <name>
   turtlemap-agent query coupling <a> <b>
   ```

Done when every changed name, function and module has been checked against all three rules, the fixes are committed, and the project's tests and type checks pass. Commits are what Turtlemap shows, so commit before touring.

## 3. Flag these, don't change them

Post a comment on the item for each of these. Leave the code as it is; the user decides.

4. **State is the enemy.** Keep as little state as possible. A value that can be derived from others shouldn't be stored, unless performance needs it, and then the cache is managed explicitly, including when it becomes invalid. For each added field or variable, ask: is this true state, or can it be derived?
5. **Elegance and simplicity.** A pile of special cases is a sign to look for a simpler solution. Think like a mathematician: what class of problem is this? A graph layout tool that collects a special case for each layout problem is solving a constraint satisfaction problem, and that field has general solutions.

## 4. Tour

Post the tour as a series of Turtlemap comments, in this order:

1. **The functional entry point** of the change, to give the context.
2. **A risk-first search** down the call tree from there: visit the riskiest code next, going breadth-first or depth-first as the risk leads.

**Every comment is at most 140 characters.** A stop summarises; when something needs pointing out, post it as its own comment on the specific item instead of lengthening the stop.

Post with the bundled script. It reads a JSON list of `{"anchor": ..., "body": ...}` from stdin, refuses the whole batch if any body is over 140 characters, and prints each new thread id:

```bash
poetry -C /path/to/turtlemap run python /path/to/turtlemap/skills/turtlemap-review/post_comments.py --root "$PWD" < comments.json
```

Anchors:

- **A function's blueprint:** `{"view": "blueprint", "path": "pkg/mod.py", "qual": "Class.method", "nodes": [], "label": "Class.method"}`
- **Items on the map:** `{"view": "map", "ids": ["fn:pkg/mod.py:func", "m:pkg/mod.py:Class.method"], "label": "what they are"}`. Other id kinds are `cls:` (class), `f:` (field, `Class.field`), `c:` (constant) and `mod:` (module). `turtlemap-agent query find <text>` prints the id of anything.

Mark the threads you post `seen` so the watcher doesn't wake on them. Done when every changed function is either a tour stop or reached from one, and every rule 4 and 5 finding has its own comment.

## 5. Answer

When the watcher wakes, `turtlemap-agent show <id>` the thread, act on it, commit, `reply`, and mark it `done` or `seen`.
