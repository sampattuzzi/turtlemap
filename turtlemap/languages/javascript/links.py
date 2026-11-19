from tree_sitter import Node as Syntax

from turtlemap.analysis import model as m
from turtlemap.languages.javascript import nodes as ts
from turtlemap.languages.javascript import literals
from turtlemap.languages.language import ImportBinding, Locate


class ModuleLinks:
    def __init__(self, path: str, name: str, locate: Locate) -> None:
        self.path = path
        self.name = name
        self._locate = locate
        self.bindings: dict[str, ImportBinding] = {}
        self.has_module_syntax = False

    def mark_module(self) -> None:
        self.has_module_syntax = True

    def find(self, specifier: str) -> str | None:
        return self._locate(specifier, self.path)

    def is_script(self, path: str, data: bytes) -> bool:
        if self.has_module_syntax or path.endswith((".mjs", ".cjs")):
            return False
        return b"require(" not in data and b"exports" not in data

    def require_call(self, node: Syntax, binding: Syntax | None) -> list[m.Stmt] | None:
        function = node.child_by_field_name("function")
        if function is None or function.type != "identifier":
            return None
        if ts.decode(function.text) != "require":
            return None
        arguments = [
            child
            for child in ts.named(ts.field(node, "arguments"))
            if child.type == "string"
        ]
        if len(arguments) != 1:
            return []
        self.mark_module()
        specifier = literals.string_value(arguments[0])
        line, end = ts.span(node)
        if binding is None:
            return self.import_of(line, end, specifier, [], node)
        if binding.type == "identifier":
            return self.import_of(
                line, end, specifier, [("*", ts.decode(binding.text))], node
            )
        if binding.type == "object_pattern":
            return self.import_of(
                line, end, specifier, list(ts.pattern_names(binding)), node
            )
        return []

    def import_statement(self, node: Syntax) -> list[m.Stmt]:
        source = node.child_by_field_name("source")
        if source is None:
            return []
        specifier = literals.string_value(source)
        names: list[tuple[str, str]] = []
        clause = next(
            (c for c in node.named_children if c.type == "import_clause"), None
        )
        if clause is not None:
            for part in clause.named_children:
                if part.type == "identifier":
                    names.append(("default", ts.decode(part.text)))
                elif part.type == "namespace_import":
                    alias = ts.first(part)
                    if alias is not None:
                        names.append(("*", ts.decode(alias.text)))
                elif part.type == "named_imports":
                    for specifier_node in part.named_children:
                        if specifier_node.type != "import_specifier":
                            continue
                        imported = ts.decode(ts.field(specifier_node, "name").text)
                        alias_node = specifier_node.child_by_field_name("alias")
                        names.append(
                            (
                                imported,
                                ts.decode(alias_node.text) if alias_node else imported,
                            )
                        )
        line, end = ts.span(node)
        return self.import_of(line, end, specifier, names, node)

    def import_of(
        self,
        line: int,
        end: int,
        specifier: str,
        names: list[tuple[str, str]],
        node: Syntax,
    ) -> list[m.Stmt]:
        located = self.find(specifier)
        if located is None and specifier.startswith("."):
            return []
        target = located if located is not None else _package(specifier)
        whole = [alias for imported, alias in names if _whole(imported, located)]
        named = [
            (imported, alias)
            for imported, alias in names
            if not _whole(imported, located)
        ]
        out: list[m.Stmt] = []
        if whole:
            out.append(_whole_import(line, end, target, whole, node))
        if named or not whole:
            out.append(_named_import(line, end, target, named, node))
        return out

    def alias(self, exported: str, local: str) -> None:
        self.bindings[exported] = ImportBinding(f"{self.name}.{local}", False)


def _package(specifier: str) -> str:
    parts = specifier.split("/")
    head = 2 if specifier.startswith("@") and len(parts) > 1 else 1
    package = "/".join(parts[:head])
    rest = parts[head:]
    return ".".join([package, *rest])


def _whole(imported: str, located: str | None) -> bool:
    return imported == "*" or (located is None and imported == "default")


def _whole_import(
    line: int, end: int, target: str, aliases: list[str], node: Syntax
) -> m.Import:
    return m.Import(
        line,
        end,
        None,
        [m.ImportName(line, end, target, alias) for alias in aliases],
        whole=True,
        origin=node,
    )


def _named_import(
    line: int, end: int, target: str, names: list[tuple[str, str]], node: Syntax
) -> m.Import:
    return m.Import(
        line,
        end,
        target,
        [
            m.ImportName(line, end, imported, None if alias == imported else alias)
            for imported, alias in names
        ],
        origin=node,
    )
