import ast
import os
import subprocess
import sys
import threading
import warnings
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

EXCLUDED_DIRECTORIES = frozenset(
    {
        "node_modules",
        "__pycache__",
        "site-packages",
        "venv",
        "build",
        "dist",
        "dist-packages",
    }
)
STDLIB_MODULES = frozenset(sys.stdlib_module_names)
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
    node: ast.FunctionDef | ast.AsyncFunctionDef
    class_qualname: str | None


@dataclass(frozen=True)
class ParsedClass:
    qualname: str
    node: ast.ClassDef
    methods: dict[str, str]


@dataclass(frozen=True)
class ImportBinding:
    absolute: str
    is_module: bool


@dataclass
class ParsedModule:
    path: str
    name: str
    source: str
    lines: list[str]
    tree: ast.Module
    imports: dict[str, ImportBinding] = field(default_factory=dict)
    import_statements: list[ast.Import | ast.ImportFrom] = field(default_factory=list)
    classes: dict[str, ParsedClass] = field(default_factory=dict)
    functions: dict[str, ParsedFunction] = field(default_factory=dict)
    top_level: dict[str, str] = field(default_factory=dict)

    @property
    def package(self) -> str:
        if self.path.endswith("__init__.py"):
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
        self._set_files(files)

    @classmethod
    def discover(cls, root: Path) -> "Workspace":
        return cls(root, python_files_under(root))

    @property
    def files(self) -> tuple[str, ...]:
        return self._files

    def refresh(self) -> None:
        with self._lock:
            self._validated.clear()
            self._resolutions.clear()
            self._bases.clear()
        self._set_files(python_files_under(self.root))

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
        result = _parse(path, absolute)
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
        candidates = self._modules_by_suffix.get(dotted)
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

    def is_package(self, dotted: str) -> bool:
        return dotted in self._packages_by_suffix

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
        binding = module.imports.get(head)
        if binding is None:
            return None
        absolute = binding.absolute + ("." + rest if rest else "")
        return self.resolve_absolute(absolute, near=module.path)

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
        if self.is_package(dotted):
            return None
        for split in range(len(parts), 0, -1):
            if self.is_package(".".join(parts[:split])):
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
            target = base.value if isinstance(base, ast.Subscript) else base
            dotted = dotted_name(target)
            label = ast.unparse(base)
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
        self._files = tuple(sorted(set(files)))
        self._file_set = frozenset(self._files)
        suffixes: dict[str, list[str]] = {}
        packages: set[str] = set()
        for path in self._files:
            parts = module_name_for(path).split(".")
            for start in range(len(parts)):
                suffixes.setdefault(".".join(parts[start:]), []).append(path)
            directory = parts if path.endswith("__init__.py") else parts[:-1]
            for start in range(len(directory)):
                for end in range(start + 1, len(directory) + 1):
                    packages.add(".".join(directory[start:end]))
        self._modules_by_suffix = suffixes
        self._packages_by_suffix = frozenset(packages)

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
        return None


def python_files_under(root: Path) -> list[str]:
    tracked = _git_python_files(root)
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
            if filename.endswith(".py"):
                found.append(Path(directory, filename).relative_to(root).as_posix())
    return found


def module_name_for(path: str) -> str:
    without_suffix = path[: -len(".py")] if path.endswith(".py") else path
    parts = [part for part in PurePosixPath(without_suffix).parts if part]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def dotted_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted_name(node.value)
        return f"{base}.{node.attr}" if base is not None else None
    return None


def library_of(module: str) -> str:
    top = module.split(".")[0]
    return "stdlib" if top in STDLIB_MODULES else top


def _parse(path: str, absolute: Path) -> ParsedModule | ParseFailure:
    try:
        source = absolute.read_text(encoding="utf-8")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(source, filename=path)
    except (
        OSError,
        UnicodeDecodeError,
        SyntaxError,
        ValueError,
        RecursionError,
    ) as error:
        return ParseFailure(path, f"{type(error).__name__}: {error}")
    module = ParsedModule(
        path=path,
        name=module_name_for(path),
        source=source,
        lines=source.splitlines(),
        tree=tree,
    )
    _collect_imports(module)
    _collect_definitions(module, tree.body, prefix="", class_qualname=None)
    return module


def _git_python_files(root: Path) -> list[str] | None:
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
                "*.py",
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
        path for path in paths if not _is_excluded(path) and (root / path).is_file()
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


def _collect_imports(module: ParsedModule) -> None:
    for node in ast.walk(module.tree):
        if isinstance(node, ast.Import):
            module.import_statements.append(node)
            for alias in node.names:
                if alias.asname:
                    module.imports[alias.asname] = ImportBinding(alias.name, True)
                else:
                    head = alias.name.partition(".")[0]
                    module.imports.setdefault(head, ImportBinding(head, True))
        elif isinstance(node, ast.ImportFrom):
            base = _import_from_base(module, node)
            if base is None:
                continue
            module.import_statements.append(node)
            for alias in node.names:
                if alias.name == "*":
                    continue
                module.imports[alias.asname or alias.name] = ImportBinding(
                    f"{base}.{alias.name}" if base else alias.name, False
                )


def import_from_base(module: ParsedModule, node: ast.ImportFrom) -> str | None:
    return _import_from_base(module, node)


def _import_from_base(module: ParsedModule, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module or ""
    package_parts = module.package.split(".") if module.package else []
    if node.level - 1 > len(package_parts):
        return None
    kept = package_parts[: len(package_parts) - (node.level - 1)]
    if node.module:
        kept.append(node.module)
    return ".".join(kept)


def _is_overload_stub(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        dotted_name(decorator) in ("overload", "typing.overload")
        for decorator in node.decorator_list
    )


def _collect_definitions(
    module: ParsedModule,
    body: Sequence[ast.stmt],
    *,
    prefix: str,
    class_qualname: str | None,
) -> None:
    for statement in body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qualname = prefix + statement.name
            existing = module.functions.get(qualname)
            if existing is None or _is_overload_stub(existing.node):
                module.functions[qualname] = ParsedFunction(
                    qualname, statement, class_qualname
                )
            if class_qualname is not None:
                module.classes[class_qualname].methods.setdefault(
                    statement.name, qualname
                )
            elif not prefix:
                module.top_level[statement.name] = qualname
        elif isinstance(statement, ast.ClassDef):
            qualname = prefix + statement.name
            module.classes[qualname] = ParsedClass(qualname, statement, {})
            if not prefix:
                module.top_level[statement.name] = qualname
            _collect_definitions(
                module, statement.body, prefix=qualname + ".", class_qualname=qualname
            )
        elif (
            isinstance(statement, (ast.If, ast.Try))
            and class_qualname is None
            and not prefix
        ):
            nested: list[ast.stmt] = list(statement.body) + list(statement.orelse)
            if isinstance(statement, ast.Try):
                nested += list(statement.finalbody)
                for handler in statement.handlers:
                    nested += handler.body
            _collect_definitions(module, nested, prefix=prefix, class_qualname=None)
