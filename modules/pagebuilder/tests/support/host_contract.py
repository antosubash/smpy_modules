import ast
import inspect
import textwrap

_REFLECTION = frozenset({"getattr", "hasattr", "setattr"})


def _self_members(tree: ast.AST) -> set[str]:
    """Every ``self.<name>`` and ``getattr/hasattr/setattr(self, "<name>")``.

    A reflective call whose name is not a string literal cannot be checked, so
    it is reported as ``<dynamic getattr>`` (etc.) and fails the scan.
    """
    used: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        ):
            used.add(node.attr)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _REFLECTION
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "self"
        ):
            name = node.args[1]
            if isinstance(name, ast.Constant) and isinstance(name.value, str):
                used.add(name.value)
            else:
                used.add(f"<dynamic {node.func.id}>")
    return used


def _undeclared(mixin: type, host: type) -> set[str]:
    """Members *mixin* uses on ``self`` that neither its MRO nor *host* defines."""
    used = _self_members(ast.parse(textwrap.dedent(inspect.getsource(mixin))))
    own = {name for klass in mixin.__mro__ if klass is not object for name in vars(klass)}
    declared = {
        name
        for klass in host.__mro__
        if klass is not object
        for name in (*vars(klass), *inspect.get_annotations(klass))
    }
    return used - own - declared
