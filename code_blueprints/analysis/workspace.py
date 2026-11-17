import os
import subprocess
import threading
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from code_blueprints.analysis import model as m
from code_blueprints.languages.aliases import PathAliases
from code_blueprints.languages.language import ImportBinding, Language, Locate
from code_blueprints.languages.registry import (
    EXTENSIONS,
    STDLIB_MODULES,
    language_for,
)

EXCLUDED_DIRECTORIES = frozenset(
    {
        "node_modules",
        "__pycache__",
        "node_modules",
        "site-packages",
        "venv",
        "build",
        "dist",
        "dist-packages",
    }
)
_MAX_RESOLUTION_DEPTH = 6


@dataclass(frozen=True)
class SymbolRef:
    path: str
    sym: str

    def to_json(self) -> dict[str, str]:
        return {"path": self.path, "sym": self.sym}


@dataclass(frozen=True)
class ModuleRef:
    path: str


@dataclass(frozen=True)
class ExternalRef:
    module: str
    name: str | None


Resolved = SymbolRef | ModuleRef | ExternalRef


@dataclass(frozen=True)
class ParsedFunction:
    qualname: str
    node: m.FunctionDecl
    class_qualname: str | None


@dataclass(frozen=True)
class ParsedClass:
    qualname: str
    node: m.ClassDecl
    methods: dict[str, str]


@dataclass
class ParsedModule:
    path: str
    name: str
    source: str
    lines: list[str]
    code: m.ModuleCode
    imports: dict[str, ImportBinding] = field(default_factory=dict)
    import_statements: list[m.Import] = field(default_factory=list)
    star_imports: list[str] = field(default_factory=list)
    classes: dict[str, ParsedClass] = field(default_factory=dict)
    functions: dict[str, ParsedFunction] = field(default_factory=dict)
    top_level: dict[str, str] = field(default_factory=dict)

    @property
    def body(self) -> list[m.Stmt]:
        return self.code.body

    @property
    def language(self) -> Language:
        return self.code.language

    @property
    def package(self) -> str:
        if self.language.is_package_init(self.path):
            return self.name
        return self.name.rpartition(".")[0]


@dataclass(frozen=True)
class ParseFailure:
    path: str
    message: str


class Workspace:
    def __init__(self, root: Path, files: Iterable[str]) -> None:
        self.root = root.resolve()
        self._parsed: dict[str, tuple[float, ParsedModule | ParseFailure]] = {}
        self._validated: set[str] = set()
        self._resolutions: dict[tuple[str, str], Resolved | None] = {}
        self._bases: dict[SymbolRef, tuple[tuple[str, Resolved | None], ...]] = {}
        self._lock = threading.RLock()
        self._aliases = PathAliases(self.root)
        self._scripts: dict[str, tuple[str, ...]] = {}
        self._set_files(files)

    @classmethod
    def discover(cls, root: Path) -> "Workspace":
        return cls(root, source_files_under(root))

    @property
    def files(self) -> tuple[str, ...]:
        return self._files

    def refresh(self) -> None:
        with self._lock:
            self._validated.clear()
            self._resolutions.clear()
            self._bases.clear()
            self._aliases = PathAliases(self.root)
        self._set_files(source_files_under(self.root))

    def contains(self, path: str) -> bool:
        return path in self._file_set

    def parsed(self, path: str) -> ParsedModule | ParseFailure:
        cached_now = self._parsed.get(path)
        if cached_now is not None and path in self._validated:
            return cached_now[1]
        absolute = self.root / path
        try:
            modified = absolute.stat().st_mtime
        except OSError as error:
            return ParseFailure(path, str(error))
        with self._lock:
            cached = self._parsed.get(path)
            if cached is not None and cached[0] == modified:
                self._validated.add(path)
                return cached[1]
        result = _parse(path, absolute, self.locate)
        with self._lock:
            self._parsed[path] = (modified, result)
            self._validated.add(path)
            self._resolutions.clear()
            self._bases.clear()
        return result

    def module(self, path: str) -> ParsedModule | None:
        result = self.parsed(path)
        return result if isinstance(result, ParsedModule) else None

    def find_module(self, dotted: str, *, near: str) -> str | None:
        candidates = self._modules_by_suffix.get((_language_name(near), dotted))
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        near_parts = PurePosixPath(near).parts
        return max(
            candidates,
            key=lambda candidate: (
                _shared_prefix(PurePosixPath(candidate).parts, near_parts),
                -len(candidate),
            ),
        )

    def is_package(self, dotted: str, *, near: str) -> bool:
        return (_language_name(near), dotted) in self._packages_by_suffix

    def resolve(self, module: ParsedModule, dotted: str) -> Resolved | None:
        key = (module.path, dotted)
        if key in self._resolutions:
            return self._resolutions[key]
        result = self._resolve(module, dotted)
        self._resolutions[key] = result
        return result

    def _resolve(self, module: ParsedModule, dotted: str) -> Resolved | None:
        head, _, rest = dotted.partition(".")
        if head in module.top_level:
            return self._lookup(module.path, dotted.split("."), 0)
        if rest and (dotted in module.functions or dotted in module.classes):
            return SymbolRef(module.path, dotted)
        binding = module.imports.get(head)
        if binding is None:
            owner = self.script_owner(module, head)
            if owner is None:
                return None
            return self._lookup(owner.path, dotted.split("."), 0)
        absolute = binding.absolute + ("." + rest if rest else "")
        return self.resolve_absolute(absolute, near=module.path)

    def script_owner(self, module: ParsedModule, name: str) -> ParsedModule | None:
        for neighbour in self.script_neighbours(module):
            if name in neighbour.top_level:
                return neighbour
        return None

    def script_neighbours(self, module: ParsedModule) -> list[ParsedModule]:
        if not module.code.is_script:
            return []
        directory = PurePosixPath(module.path).parent.as_posix()
        paths = self._scripts.get(directory)
        if paths is None:
            paths = tuple(
                path
                for path in self._files
                if PurePosixPath(path).parent.as_posix() == directory
                and language_for(path) is module.language
            )
            self._scripts[directory] = paths
        neighbours: list[ParsedModule] = []
        for path in paths:
            if path == module.path:
                continue
            neighbour = self.module(path)
            if neighbour is not None and neighbour.code.is_script:
                neighbours.append(neighbour)
        return neighbours

    def resolve_absolute(
        self, dotted: str, *, near: str, depth: int = 0
    ) -> Resolved | None:
        if depth > _MAX_RESOLUTION_DEPTH or not dotted:
            return None
        parts = dotted.split(".")
        for split in range(len(parts), 0, -1):
            path = self.find_module(".".join(parts[:split]), near=near)
            if path is None:
                continue
            if split == len(parts):
                return ModuleRef(path)
            found = self._lookup(path, parts[split:], depth + 1)
            if found is not None:
                return found
            return None
        if self.is_package(dotted, near=near):
            return None
        for split in range(len(parts), 0, -1):
            if self.is_package(".".join(parts[:split]), near=near):
                return None
        return ExternalRef(
            parts[0] if len(parts) == 1 else ".".join(parts[:-1]),
            parts[-1] if len(parts) > 1 else None,
        )

    def parsed_class(self, ref: SymbolRef) -> ParsedClass | None:
        module = self.module(ref.path)
        return module.classes.get(ref.sym) if module else None

    def parsed_function(self, ref: SymbolRef) -> ParsedFunction | None:
        module = self.module(ref.path)
        return module.functions.get(ref.sym) if module else None

    def base_classes(self, ref: SymbolRef) -> tuple[tuple[str, Resolved | None], ...]:
        if ref not in self._bases:
            self._bases[ref] = self._base_classes(ref)
        return self._bases[ref]

    def _base_classes(self, ref: SymbolRef) -> tuple[tuple[str, Resolved | None], ...]:
        parsed = self.parsed_class(ref)
        module = self.module(ref.path)
        if parsed is None or module is None:
            return ()
        bases: list[tuple[str, Resolved | None]] = []
        for base in parsed.node.bases:
            target = base.value if isinstance(base, m.Subscript) else base
            dotted = m.dotted_name(target)
            label = module.language.text(base)
            if dotted is None:
                bases.append((label, None))
                continue
            owner, _, _ = parsed.qualname.rpartition(".")
            if owner and f"{owner}.{dotted}" in module.classes:
                bases.append((label, SymbolRef(module.path, f"{owner}.{dotted}")))
                continue
            bases.append((label, self.resolve(module, dotted)))
        return tuple(bases)

    def find_method(
        self, ref: SymbolRef, name: str, *, depth: int = 0
    ) -> SymbolRef | None:
        if depth > _MAX_RESOLUTION_DEPTH:
            return None
        parsed = self.parsed_class(ref)
        if parsed is None:
            return None
        if name in parsed.methods:
            return SymbolRef(ref.path, parsed.methods[name])
        for _, base in self.base_classes(ref):
            if isinstance(base, SymbolRef) and self.parsed_class(base) is not None:
                found = self.find_method(base, name, depth=depth + 1)
                if found is not None:
                    return found
        return None

    def class_ancestry(self, ref: SymbolRef) -> list[SymbolRef]:
        seen: list[SymbolRef] = []
        pending = [ref]
        while pending and len(seen) < 32:
            current = pending.pop(0)
            if current in seen:
                continue
            seen.append(current)
            pending.extend(
                base
                for _, base in self.base_classes(current)
                if isinstance(base, SymbolRef) and self.parsed_class(base) is not None
            )
        return seen

    def _set_files(self, files: Iterable[str]) -> None:
        previous = getattr(self, "_file_set", None)
        self._files = tuple(sorted(set(files)))
        self._file_set = frozenset(self._files)
        if previous is not None and previous != self._file_set:
            self._forget_parses_that_read_other_files()
        suffixes: dict[tuple[str, str], list[str]] = {}
        packages: set[tuple[str, str]] = set()
        for path in self._files:
            parts = module_name_for(path).split(".")
            language = language_for(path)
            name = _language_name(path)
            for start in range(len(parts)):
                suffixes.setdefault((name, ".".join(parts[start:])), []).append(path)
            is_init = language is not None and language.is_package_init(path)
            directory = parts if is_init else parts[:-1]
            for start in range(len(directory)):
                for end in range(start + 1, len(directory) + 1):
                    packages.add((name, ".".join(directory[start:end])))
        self._modules_by_suffix = suffixes
        self._packages_by_suffix = frozenset(packages)
        self._scripts = {}

    def _forget_parses_that_read_other_files(self) -> None:
        with self._lock:
            for path in list(self._parsed):
                language = language_for(path)
                if language is not None and language.reads_other_files:
                    del self._parsed[path]

    def locate(self, specifier: str, near: str) -> str | None:
        if specifier.startswith("."):
            target = PurePosixPath(near).parent / specifier
            bases = [os.path.normpath(target.as_posix()).replace(os.sep, "/")]
        else:
            bases = self._aliases.candidates(specifier, near)
        for normal in bases:
            if normal.startswith(".."):
                continue
            for candidate in (
                normal,
                *(normal + ext for ext in EXTENSIONS),
                *(f"{normal}/index{ext}" for ext in EXTENSIONS),
            ):
                if candidate in self._file_set:
                    return module_name_for(candidate)
        return None

    def _lookup(self, path: str, parts: Sequence[str], depth: int) -> Resolved | None:
        module = self.module(path)
        if module is None or not parts:
            return None
        joined = ".".join(parts)
        if joined in module.classes or joined in module.functions:
            return SymbolRef(path, joined)
        head = parts[0]
        if head in module.classes and len(parts) >= 2:
            return self.find_method(SymbolRef(path, head), parts[1]) or SymbolRef(
                path, head
            )
        binding = module.imports.get(head)
        if binding is not None and depth <= _MAX_RESOLUTION_DEPTH:
            rest = ".".join(parts[1:])
            return self.resolve_absolute(
                binding.absolute + ("." + rest if rest else ""),
                near=path,
                depth=depth + 1,
            )
        if depth > _MAX_RESOLUTION_DEPTH:
            return None
        for star in module.star_imports:
            target = self.find_module(star, near=path)
            if target is None or target == path:
                continue
            found = self._lookup(target, parts, depth + 1)
            if found is not None:
                return found
        return None


def source_files_under(root: Path) -> list[str]:
    tracked = _git_source_files(root)
    if tracked is not None:
        return tracked
    found: list[str] = []
    for directory, subdirectories, filenames in os.walk(root):
        subdirectories[:] = [
            name
            for name in subdirectories
            if not name.startswith(".") and name not in EXCLUDED_DIRECTORIES
        ]
        for filename in filenames:
            relative = Path(directory, filename).relative_to(root).as_posix()
            if _is_source(relative):
                found.append(relative)
    return found


def module_name_for(path: str) -> str:
    language = language_for(path)
    if language is None:
        return ".".join(part for part in PurePosixPath(path).parts if part)
    return language.module_name(path)


def library_of(module: str) -> str:
    top = module.split(".")[0]
    return "stdlib" if top in STDLIB_MODULES else top


def _language_name(path: str) -> str:
    language = language_for(path)
    return language.name if language is not None else ""


def _is_source(path: str) -> bool:
    language = language_for(path)
    return language is not None and language.includes(path)


def _parse(path: str, absolute: Path, locate: Locate) -> ParsedModule | ParseFailure:
    language = language_for(path)
    if language is None:
        return ParseFailure(path, "Not a supported language")
    errors: tuple[type[Exception], ...] = (
        OSError,
        UnicodeDecodeError,
        *language.parse_errors(),
    )
    try:
        source = absolute.read_text(encoding="utf-8")
        name = module_name_for(path)
        lowered = language.lower(path, name, source, locate)
    except errors as error:
        return ParseFailure(path, f"{type(error).__name__}: {error}")
    module = ParsedModule(
        path=path,
        name=name,
        source=source,
        lines=source.splitlines(),
        code=lowered.code,
    )
    _collect_imports(module, lowered.imports)
    _collect_definitions(module, module.body, prefix="", class_qualname=None)
    return module


def _git_source_files(root: Path) -> list[str] | None:
    try:
        completed = subprocess.run(
            [
                "git",
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
                "--",
                *(f"*{extension}" for extension in EXTENSIONS),
            ],
            cwd=root,
            capture_output=True,
            check=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    paths = [
        entry
        for entry in completed.stdout.decode("utf-8", "replace").split("\0")
        if entry
    ]
    return [
        path
        for path in paths
        if not _is_excluded(path) and _is_source(path) and (root / path).is_file()
    ]


def _is_excluded(path: str) -> bool:
    return any(
        part in EXCLUDED_DIRECTORIES or part.startswith(".")
        for part in PurePosixPath(path).parts[:-1]
    )


def _shared_prefix(left: Sequence[str], right: Sequence[str]) -> int:
    count = 0
    for left_part, right_part in zip(left, right):
        if left_part != right_part:
            break
        count += 1
    return count


def _collect_imports(module: ParsedModule, extra: dict[str, ImportBinding]) -> None:
    pending: deque[m.Node] = deque(module.body)
    while pending:
        node = pending.popleft()
        pending.extend(
            child
            for child in m.children(node)
            if not isinstance(child, (m.Expr, m.TypeExpr))
        )
        if not isinstance(node, m.Import):
            continue
        if node.whole:
            module.import_statements.append(node)
            for alias in node.names:
                if alias.alias:
                    module.imports[alias.alias] = ImportBinding(alias.name, True)
                else:
                    head = alias.name.partition(".")[0]
                    module.imports.setdefault(head, ImportBinding(head, True))
            continue
        base = node.module
        if base is None:
            continue
        module.import_statements.append(node)
        for alias in node.names:
            if alias.name == "*":
                if module.language.profile.follows_star_imports:
                    module.star_imports.append(base)
                continue
            module.imports[alias.alias or alias.name] = ImportBinding(
                f"{base}.{alias.name}" if base else alias.name, False
            )
    module.imports.update(extra)


def _collect_definitions(
    module: ParsedModule,
    body: Sequence[m.Stmt],
    *,
    prefix: str,
    class_qualname: str | None,
) -> None:
    for statement in body:
        if isinstance(statement, m.FunctionDef):
            function = statement.function
            qualname = prefix + function.name
            existing = module.functions.get(qualname)
            if existing is None or existing.node.is_overload:
                module.functions[qualname] = ParsedFunction(
                    qualname, function, class_qualname
                )
            if class_qualname is not None:
                module.classes[class_qualname].methods.setdefault(
                    function.name, qualname
                )
            elif not prefix:
                module.top_level[function.name] = qualname
        elif isinstance(statement, m.ClassDef):
            qualname = prefix + statement.cls.name
            module.classes[qualname] = ParsedClass(qualname, statement.cls, {})
            if not prefix:
                module.top_level[statement.cls.name] = qualname
            _collect_definitions(
                module,
                statement.cls.body,
                prefix=qualname + ".",
                class_qualname=qualname,
            )
        elif (
            isinstance(statement, (m.If, m.Try))
            and class_qualname is None
            and not prefix
        ):
            nested: list[m.Stmt] = list(statement.body)
            if isinstance(statement, m.If):
                nested += statement.orelse
            else:
                nested += list(statement.orelse) + list(statement.finalbody)
                for handler in statement.handlers:
                    nested += handler.body
            _collect_definitions(module, nested, prefix=prefix, class_qualname=None)
