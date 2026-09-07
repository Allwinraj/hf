from __future__ import annotations

import ast
import operator
from decimal import Decimal
from typing import Any

ALLOWED_FUNCS: dict[str, Any] = {
    "min": min,
    "max": max,
    "abs": abs,
    "len": len,
    "sum": sum,
    "bool": bool,
    "str": str,
    "int": int,
}

_BIN: dict[type[ast.operator], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY: dict[type[ast.unaryop], Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
}
_CMP: dict[type[ast.cmpop], Any] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}


class SandboxError(ValueError):
    """Expression uses a disallowed construct."""


def _to_decimal(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    return value


class AstSandbox:
    def validate(self, expression: str) -> None:
        tree = ast.parse(expression, mode="eval")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_FUNCS:
                    raise SandboxError("only whitelisted functions may be called")
                if node.keywords:
                    raise SandboxError("keyword arguments are not allowed")
            elif isinstance(
                node,
                (
                    ast.Attribute,
                    ast.Lambda,
                    ast.ListComp,
                    ast.SetComp,
                    ast.DictComp,
                    ast.GeneratorExp,
                    ast.Yield,
                    ast.Await,
                    ast.NamedExpr,
                ),
            ):
                raise SandboxError(f"{type(node).__name__} is not allowed")

    def eval(self, expression: str, names: dict[str, Any] | None = None) -> Any:
        tree = ast.parse(expression, mode="eval")
        return self._eval(tree.body, names or {})

    def _eval(self, node: ast.AST, names: dict[str, Any]) -> Any:
        if isinstance(node, ast.Constant):
            return _to_decimal(node.value) if isinstance(node.value, (int, float)) else node.value
        if isinstance(node, ast.Name):
            if node.id not in names:
                raise SandboxError(f"unknown name {node.id!r}")
            return names[node.id]
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](self._eval(node.operand, names))
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            left = self._eval(node.left, names)
            right = self._eval(node.right, names)
            return _BIN[type(node.op)](left, right)
        if isinstance(node, ast.BoolOp):
            values = [self._eval(v, names) for v in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            if isinstance(node.op, ast.Or):
                return any(values)
        if isinstance(node, ast.Compare):
            left = self._eval(node.left, names)
            for op, comparator in zip(node.ops, node.comparators, strict=True):
                right = self._eval(comparator, names)
                fn = _CMP.get(type(op))
                if fn is None:
                    raise SandboxError(f"operator {type(op).__name__} is not allowed")
                if not fn(left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            cond = self._eval(node.test, names)
            return self._eval(node.body if cond else node.orelse, names)
        if isinstance(node, ast.List):
            return [self._eval(elt, names) for elt in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(self._eval(elt, names) for elt in node.elts)
        if isinstance(node, ast.Dict):
            return {
                self._eval(k, names): self._eval(v, names)
                for k, v in zip(node.keys, node.values, strict=True)
                if k is not None
            }
        if isinstance(node, ast.Subscript):
            value = self._eval(node.value, names)
            sl = node.slice
            key = self._eval(sl, names)
            return value[key]
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_FUNCS:
                raise SandboxError("only whitelisted functions may be called")
            if node.keywords:
                raise SandboxError("keyword arguments are not allowed")
            args = [self._eval(a, names) for a in node.args]
            return ALLOWED_FUNCS[node.func.id](*args)
        raise SandboxError(f"{type(node).__name__} is not allowed")


SANDBOX = AstSandbox()


def eval_expr(expression: str, names: dict[str, Any] | None = None) -> Any:
    return SANDBOX.eval(expression, names)


def validate_expr(expression: str) -> None:
    SANDBOX.validate(expression)
