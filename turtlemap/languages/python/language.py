import ast
import copy
import warnings
from collections.abc import Mapping
from typing import Any

from turtlemap.analysis import model as m
from turtlemap.languages.language import (
    Language,
    Locate,
    Lowered,
    TypeParameter,
    stem_parts,
)
from turtlemap.languages.python.definitions import doc_lines
from turtlemap.languages.python.lowering import Lowering
from turtlemap.languages.python.profile import PYTHON_PROFILE, PYTHON_SYNTAX


class Python(Language):
    name = "python"
    extensions = (".py",)
    profile = PYTHON_PROFILE
    syntax = PYTHON_SYNTAX

    def module_name(self, path: str) -> str:
        parts = stem_parts(path, self.extensions)
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        return ".".join(parts)

    def is_package_init(self, path: str) -> bool:
        return path.endswith("__init__.py")

    def lower(self, path: str, name: str, source: str, locate: Locate) -> Lowered:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(source, filename=path)
        package = name if self.is_package_init(path) else name.rpartition(".")[0]
        lowering = Lowering(package)
        body = lowering.block(tree.body)
        code = m.ModuleCode(
            body=body,
            doc=ast.get_docstring(tree),
            doc_lines=doc_lines(tree.body),
        )
        return Lowered(code, lowering.imports)

    def text(self, node: m.Node) -> str:
        origin = node.origin
        if isinstance(origin, ast.AST):
            return ast.unparse(origin)
        if isinstance(origin, str):
            return origin
        return ""

    def text_with(self, node: m.Node, replacements: Mapping[m.Node, str]) -> str:
        origin = node.origin
        if not isinstance(origin, ast.AST):
            return replacements.get(node) or self.text(node)
        names = {
            id(key.origin): name
            for key, name in replacements.items()
            if isinstance(key.origin, ast.AST)
        }
        memo: dict[int, Any] = {}
        copied = copy.deepcopy(origin, memo)
        renamed = {id(memo[key]): name for key, name in names.items() if key in memo}
        result: ast.AST = _Renamer(renamed).visit(copied)
        return ast.unparse(result)

    def literal_text(self, value: object) -> str:
        if value is ...:
            return "..."
        if value is None or isinstance(value, (str, bytes, bool, int, float, complex)):
            return ast.unparse(ast.Constant(value))
        return repr(value)

    def is_constant(self, statement: m.Assign) -> bool:
        if len(statement.targets) != 1:
            return False
        target = statement.targets[0]
        if not isinstance(target, m.Name):
            return False
        if statement.annotation is not None:
            return statement.value is not None
        bare = target.id.lstrip("_")
        return bool(bare) and bare.isupper() and self.type_parameter(statement) is None

    def type_parameter(self, statement: m.Assign) -> TypeParameter | None:
        value = statement.value
        if (
            len(statement.targets) != 1
            or not isinstance(statement.targets[0], m.Name)
            or not isinstance(value, m.Call)
        ):
            return None
        called = m.dotted_name(value.func) or ""
        if called.rsplit(".", 1)[-1] not in _TYPE_PARAMETER_MAKERS:
            return None
        bound = next(
            (keyword.value for keyword in value.keywords if keyword.arg == "bound"),
            None,
        )
        return TypeParameter(statement.targets[0].id, bound, tuple(value.args[1:]))


_TYPE_PARAMETER_MAKERS = frozenset({"TypeVar", "ParamSpec", "TypeVarTuple"})


class _Renamer(ast.NodeTransformer):
    def __init__(self, names: dict[int, str]) -> None:
        self.names = names

    def visit(self, node: ast.AST) -> Any:
        name = self.names.get(id(node))
        return ast.Name(name) if name is not None else super().visit(node)
