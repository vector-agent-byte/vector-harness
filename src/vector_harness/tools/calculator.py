"""只做四则运算的计算器。

表达式用语法树求值，只允许数字和加减乘除。名字、函数调用和属性访问都会拒绝。
"""

from __future__ import annotations

import ast
import operator
from dataclasses import dataclass, field

_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _eval_node(node: ast.AST) -> int | float:
    """只走数字、一元正负号和二元运算。其它节点一律拒绝。"""
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    raise ValueError("unsupported expression")


def evaluate(expression: str) -> str:
    """算出结果。整数结果不带小数点。非法表达式返回 ``Error:`` 开头的文本。"""
    try:
        value = _eval_node(ast.parse(expression, mode="eval"))
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError):
        return "Error: unsupported expression"
    # 8/2 得到 4.0。整数值去掉小数点，模型可以直接引用。
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


@dataclass
class Calculator:
    """给模型调用的计算器。参数是一条算术表达式，例如 ``2 + 3 * 4``。"""

    name: str = "calculator"
    description: str = "Evaluate an arithmetic expression such as 2 + 3 * 4."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Arithmetic expression using numbers and + - * /.",
                }
            },
            "required": ["expression"],
        }
    )

    async def execute(self, arguments: dict) -> str:
        """求值。缺表达式或表达式不合法时返回错误文本，不抛异常。"""
        expression = arguments.get("expression")
        if not isinstance(expression, str) or not expression.strip():
            return "Error: expression is required"
        return evaluate(expression)
