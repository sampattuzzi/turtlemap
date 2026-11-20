import threading
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from turtlemap.analysis import model as m
from turtlemap.analysis.workspace.files import source_files_under
from turtlemap.analysis.workspace.index import ModuleIndex
from turtlemap.analysis.workspace.parsed import (
    ExternalRef,
    ModuleRef,
    ParsedClass,
    ParsedFunction,
    ParsedModule,
    ParseFailure,
    Resolved,
    SymbolRef,
    parse_module,
)
from turtlemap.analysis.workspace.reads import Keys, ReadLog, source_key
from turtlemap.languages.registry import language_for

_MAX_RESOLUTION_DEPTH = 6

Stamp = tuple[int, int]


class Workspace:
    def __init__(self, root: Path, files: Iterable[str]) -> None:
        self.root = root.resolve()
        self.reads = ReadLog()
        self._parsed: dict[str, tuple[Stamp, ParsedModule | ParseFailure, Keys]] = {}
        self._validated: set[str] = set()
        self._resolutions: dict[tuple[str, str], tuple[Resolved | None, Keys]] = {}
        self._bases: dict[
            SymbolRef, tuple[tuple[tuple[str, Resolved | None], ...], Keys]
        ] = {}
        self._lock = threading.RLock()
        self.index = ModuleIndex(self.root, files, self.reads)

    @classmethod
    def discover(cls, root: Path) -> "Workspace":
        return cls(root, source_files_under(root))

    def refresh(self) -> None:
        with self._lock:
            self._validated.clear()
            self._resolutions.clear()
            self._bases.clear()
        previous = self.index.files
        self.index = ModuleIndex(self.root, source_files_under(self.root), self.reads)
        if previous != self.index.files:
            self._forget_parses_that_read_other_files()

    def adopt_parses(
        self, other: "Workspace", unchanged: Callable[[Keys], bool]
    ) -> None:
        with other._lock:
            offered = list(other._parsed.items())
        with self._lock:
            for path, entry in offered:
                if path not in self._parsed and unchanged(entry[2]):
                    self._parsed[path] = entry
                    self._validated.add(path)

    def stamps(self) -> dict[str, tuple[int, int, str]]:
        with self._lock:
            return {
                path: (*stamp, result.digest)
                for path, (stamp, result, _) in self._parsed.items()
            }

    def fingerprint(self, key: str, file_digest: Callable[[str], str]) -> str | None:
        kind, _, path = key.partition(":")
        if kind != "src":
            return self.index.fingerprint(key)
        cached = self._parsed.get(path)
        return cached[1].digest if cached is not None else file_digest(path)

    def parsed(self, path: str) -> ParsedModule | ParseFailure:
        self.reads.note(source_key(path))
        cached_now = self._parsed.get(path)
        if cached_now is not None and path in self._validated:
            self.reads.note_all(cached_now[2])
            return cached_now[1]
        absolute = self.root / path
        try:
            stat = absolute.stat()
            modified = (stat.st_mtime_ns, stat.st_size)
        except OSError as error:
            return ParseFailure(path, str(error))
        with self._lock:
            cached = self._parsed.get(path)
            if cached is not None and cached[0] == modified:
                self._validated.add(path)
                self.reads.note_all(cached[2])
                return cached[1]
        with self.reads.recording() as keys:
            result = parse_module(path, absolute, self.index.locate)
        with self._lock:
            replaced = path in self._parsed
            self._parsed[path] = (
                modified,
                result,
                frozenset({source_key(path), *keys}),
            )
            self._validated.add(path)
            if replaced:
                self._resolutions.clear()
                self._bases.clear()
        return result

    def module(self, path: str) -> ParsedModule | None:
        result = self.parsed(path)
        return result if isinstance(result, ParsedModule) else None

    def resolve(self, module: ParsedModule, dotted: str) -> Resolved | None:
        return self.reads.remembered(
            self._resolutions,
            (module.path, dotted),
            lambda: self._resolve(module, dotted),
        )

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
        neighbours: list[ParsedModule] = []
        for path in self.index.files_beside(module.path):
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
            path = self.index.find_module(".".join(parts[:split]), near=near)
            if path is None:
                continue
            if split == len(parts):
                return ModuleRef(path)
            found = self._lookup(path, parts[split:], depth + 1)
            if found is not None:
                return found
            return None
        if self.index.is_package(dotted, near=near):
            return None
        for split in range(len(parts), 0, -1):
            if self.index.is_package(".".join(parts[:split]), near=near):
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
        return self.reads.remembered(self._bases, ref, lambda: self._base_classes(ref))

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

    def reads_as_property(self, ref: SymbolRef) -> bool:
        function = self.parsed_function(ref)
        module = self.module(ref.path)
        if function is None or module is None:
            return False
        return function.node.is_property or any(
            self._makes_descriptor(module, decorator)
            for decorator in function.node.decorators
        )

    def _makes_descriptor(self, module: ParsedModule, decorator: m.Expr) -> bool:
        called = isinstance(decorator, m.Call)
        dotted = m.dotted_name(
            decorator.func if isinstance(decorator, m.Call) else decorator
        )
        resolved = self.resolve(module, dotted) if dotted is not None else None
        if not isinstance(resolved, SymbolRef):
            return False
        if self.parsed_class(resolved) is not None and not called:
            return self._is_descriptor(resolved)
        function = self.parsed_function(resolved)
        owner = self.module(resolved.path)
        returns = function.node.returns if function is not None else None
        if owner is None or not isinstance(returns, m.TypeName):
            return False
        made = self.resolve(owner, returns.dotted)
        return isinstance(made, SymbolRef) and self._is_descriptor(made)

    def _is_descriptor(self, ref: SymbolRef) -> bool:
        module = self.module(ref.path)
        method = module.language.profile.descriptor_method if module else None
        return method is not None and self.find_method(ref, method) is not None

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

    def _forget_parses_that_read_other_files(self) -> None:
        with self._lock:
            for path in list(self._parsed):
                language = language_for(path)
                if language is not None and language.reads_other_files:
                    del self._parsed[path]

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
        return self._lookup_star_imports(module, parts, depth)

    def _lookup_star_imports(
        self, module: ParsedModule, parts: Sequence[str], depth: int
    ) -> Resolved | None:
        for star in module.star_imports:
            target = self.index.find_module(star, near=module.path)
            if target is None or target == module.path:
                continue
            found = self._lookup(target, parts, depth + 1)
            if found is not None:
                return found
        return None
