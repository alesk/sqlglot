from copy import deepcopy
import inspect
import weakref
import sys

from sqlglot.helper import camel_to_snake_case, ensure_list


class Expression:
    arg_types = {"this": True}
    token_type = None

    def __init__(self, **args):
        self.key = self.__class__.__name__.lower()
        self.args = args
        self._parent = None
        self.arg_key = None

    def __eq__(self, other):
        return type(self) is type(other) and self.args == other.args

    def __hash__(self):
        return hash(
            (
                self.key,
                tuple(
                    (k, tuple(v) if isinstance(v, list) else v)
                    for k, v in self.args.items()
                ),
            )
        )

    @property
    def parent(self):
        return self._parent() if self._parent else None

    @property
    def depth(self):
        if self.parent:
            return self.parent.depth + 1
        return 0

    @parent.setter
    def parent(self, new_parent):
        self._parent = weakref.ref(new_parent)

    def find(self, *expression_types):
        return next(self.find_all(*expression_types), None)

    def find_all(self, *expression_types):
        for expression, _, _ in self.walk():
            if isinstance(expression, expression_types):
                yield expression

    def walk(self, bfs=True):
        if bfs:
            yield from self.bfs()
        else:
            yield from self.dfs(self.parent, None)

    def dfs(self, parent, key):
        yield self, parent, key

        for k, v in self.args.items():
            nodes = ensure_list(v)

            for node in nodes:
                if isinstance(node, Expression):
                    yield from node.dfs(self, k)
                else:
                    yield node, self, k

    def bfs(self):
        queue = [(self, self.parent, None)]

        while queue:
            item, parent, key = queue.pop()

            yield item, parent, key

            if isinstance(item, Expression):
                for k, v in item.args.items():
                    nodes = ensure_list(v)

                    for node in nodes:
                        queue.append((node, item, k))

    def __repr__(self):
        return self.to_s()

    def sql(self, dialect=None, **opts):
        from sqlglot.dialects import Dialect

        return Dialect.get(dialect, Dialect)().generate(self, **opts)

    def to_s(self, level=0):
        indent = "" if not level else "\n"
        indent += "".join(["  "] * level)
        left = f"({self.key.upper()} "

        args = {
            k: ", ".join(
                v.to_s(level + 1) if hasattr(v, "to_s") else str(v)
                for v in ensure_list(vs)
                if v
            )
            for k, vs in self.args.items()
        }

        right = ", ".join(f"{k}: {v}" for k, v in args.items())
        right += ")"

        return indent + left + right

    def transform(self, fun, copy=True):
        """
        Recursively visits all tree nodes (excluding already transformed ones)
        and applies the given transformation function to each node.

        Args:
            fun (function): a function which takes a node as an argument and returns a
                new transformed node or the same node without modifications.
            copy (bool): if set to True a new tree instance is constructed, otherwise the tree is
                modified in place.

        Returns:
            the transformed tree.
        """
        node = deepcopy(self) if copy else self
        new_node = fun(node)

        if new_node is None:
            raise ValueError("A transformed node cannot be None")
        if not isinstance(new_node, Expression) or new_node is not node:
            return new_node

        for k, v in new_node.args.items():
            is_list_arg = isinstance(v, list)

            child_nodes = v if is_list_arg else [v]
            new_child_nodes = []

            for cn in child_nodes:
                if isinstance(cn, Expression):
                    new_child_node = cn.transform(fun, copy=False)
                    new_child_node.parent = new_node
                else:
                    new_child_node = cn
                new_child_nodes.append(new_child_node)

            new_node.args[k] = new_child_nodes if is_list_arg else new_child_nodes[0]
        return new_node


class Create(Expression):
    arg_types = {
        "this": True,
        "kind": True,
        "expression": False,
        "exists": False,
        "file_format": False,
        "temporary": False,
        "replace": False,
        "engine": False,
        "auto_increment": False,
        "character_set": False,
        "collate": False,
        "comment": False,
    }


class CharacterSet(Expression):
    arg_types = {"this": True, "default": False}


class CTE(Expression):
    arg_types = {"this": True, "expressions": True, "recursive": False}


class Column(Expression):
    arg_types = {"this": False, "table": False, "db": False, "fields": False}

    def __eq__(self, other):
        return (
            isinstance(other, Column)
            and (self.name or "").upper() == (other.name or "").upper()
            and (self.table or "").upper() == (other.table or "").upper()
            and (self.db or "").upper() == (other.db or "").upper()
            and [f.upper() for f in self.fields] == [f.upper() for f in other.fields]
        )

    def __hash__(self):
        return hash(
            (
                self.key,
                (self.name or "").upper(),
                (self.table or "").upper(),
                (self.db or "").upper(),
                tuple(f.upper() for f in self.fields),
            )
        )

    @property
    def name(self):
        return _token_arg_text(self, "this")

    @property
    def table(self):
        return _token_arg_text(self, "table")

    @property
    def db(self):
        return _token_arg_text(self, "db")

    @property
    def fields(self):
        fields = self.args.get("fields")
        return [t.text for t in fields] if fields else []


class ColumnDef(Expression):
    arg_types = {
        "this": True,
        "kind": True,
        "auto_increment": False,
        "comment": False,
        "collate": False,
        "default": False,
        "not_null": False,
        "primary": False,
    }


class Drop(Expression):
    arg_types = {"this": False, "kind": False, "exists": False}


class FileFormat(Expression):
    pass


class From(Expression):
    arg_types = {"expressions": True}


class Having(Expression):
    pass


class Hint(Expression):
    pass


class Insert(Expression):
    arg_types = {"this": True, "expression": True, "overwrite": False, "exists": False}


class Group(Expression):
    arg_types = {"expressions": True}


class Limit(Expression):
    pass


class Literal(Expression):
    def __eq__(self, other):
        return (
            isinstance(other, Literal)
            and self.text == other.text
            and self.token.token_type == other.token.token_type
        )

    def __hash__(self):
        return hash(
            (
                self.key,
                self.text,
                self.token_type,
            )
        )

    @property
    def token(self):
        return self.args.get("this")

    @property
    def text(self):
        return _token_arg_text(self, "this")


class Join(Expression):
    arg_types = {"this": True, "on": False, "side": False, "kind": False}


class Lateral(Expression):
    arg_types = {"this": True, "outer": False, "table": False, "columns": False}


class Order(Expression):
    arg_types = {"expressions": True}


class Ordered(Expression):
    arg_types = {"this": True, "desc": False}


class Table(Expression):
    arg_types = {"this": True, "db": False}


class Tuple(Expression):
    arg_types = {"expressions": True}


class Union(Expression):
    arg_types = {"this": True, "expression": True, "distinct": True}


class Unnest(Expression):
    arg_types = {
        "expressions": True,
        "ordinality": False,
        "table": False,
        "columns": False,
    }


class Update(Expression):
    arg_types = {"this": True, "expressions": True, "where": False}


class Values(Expression):
    arg_types = {"expressions": True}


class Schema(Expression):
    arg_types = {"this": True, "expressions": True}


class Select(Expression):
    arg_types = {
        "expressions": True,
        "hint": False,
        "distinct": False,
        "from": False,
        "laterals": False,
        "joins": False,
        "where": False,
        "group": False,
        "having": False,
        "order": False,
        "limit": False,
    }


class Window(Expression):
    arg_types = {"this": True, "partition": False, "order": False, "spec": False}


class WindowSpec(Expression):
    arg_types = {
        "kind": False,
        "start": False,
        "start_side": False,
        "end": False,
        "end_side": False,
    }


class Where(Expression):
    pass


class Star(Expression):
    arg_types = {}


class Null(Expression):
    arg_types = {}


# Binary Expressions
# (PLUS a b)
# (FROM table selects)
class Binary(Expression):
    arg_types = {"this": True, "expression": True}


class And(Binary):
    pass


class BitwiseAnd(Binary):
    pass


class BitwiseLeftShift(Binary):
    pass


class BitwiseOr(Binary):
    pass


class BitwiseRightShift(Binary):
    pass


class BitwiseXor(Binary):
    pass


class Minus(Binary):
    pass


class IntDiv(Binary):
    pass


class Dot(Binary):
    pass


class DPipe(Binary):
    pass


class EQ(Binary):
    pass


class GT(Binary):
    pass


class GTE(Binary):
    pass


class Is(Binary):
    pass


class Like(Binary):
    pass


class LT(Binary):
    pass


class LTE(Binary):
    pass


class Mod(Binary):
    pass


class NEQ(Binary):
    pass


class Or(Binary):
    pass


class Plus(Binary):
    pass


class Mul(Binary):
    pass


class Div(Binary):
    pass


# Unary Expressions
# (NOT a)
class Unary(Expression):
    pass


class BitwiseNot(Unary):
    pass


class Not(Unary):
    pass


class Paren(Unary):
    pass


class Neg(Unary):
    pass


# Special Functions
class Alias(Expression):
    arg_types = {"this": True, "alias": False}


class Between(Expression):
    arg_types = {"this": True, "low": True, "high": True}


class Bracket(Expression):
    arg_types = {"this": True, "expressions": True}


class Case(Expression):
    arg_types = {"this": False, "ifs": True, "default": False}


class Cast(Expression):
    arg_types = {"this": True, "to": True}


class Decimal(Expression):
    arg_types = {"precision": False, "scale": False}


class Extract(Expression):
    arg_types = {"this": True, "expression": True}


class In(Expression):
    arg_types = {"this": True, "expressions": False, "query": False}


class Interval(Expression):
    arg_types = {"this": True, "unit": True}


# Functions
class Func(Expression):
    is_var_len_args = False

    @classmethod
    def from_arg_list(cls, args):
        args_num = len(args)

        all_arg_keys = list(cls.arg_types)
        # If this function supports variable length argument treat the last argument as such.
        non_var_len_arg_keys = (
            all_arg_keys[:-1] if cls.is_var_len_args else all_arg_keys
        )

        args_dict = {}
        arg_idx = 0
        for arg_key in non_var_len_arg_keys:
            if arg_idx >= args_num:
                break
            if args[arg_idx] is not None:
                args_dict[arg_key] = args[arg_idx]
            arg_idx += 1

        if arg_idx < args_num and cls.is_var_len_args:
            args_dict[all_arg_keys[-1]] = args[arg_idx:]
        return cls(**args_dict)

    @classmethod
    def sql_names(cls):
        if cls is Func:
            raise NotImplementedError(
                "SQL name is only supported by concrete function implementations"
            )
        if not hasattr(cls, "_sql_names"):
            cls._sql_names = [camel_to_snake_case(cls.__name__)]
        return cls._sql_names

    @classmethod
    def sql_name(cls):
        return cls.sql_names()[0]

    @classmethod
    def default_parser_mappings(cls):
        return {name: cls.from_arg_list for name in cls.sql_names()}


class AggFunc(Func):
    pass


class Abs(Func):
    pass


class Anonymous(Func):
    arg_types = {"this": True, "expressions": False}
    is_var_len_args = True


class ApproxDistinct(AggFunc):
    arg_types = {"this": True, "accuracy": False}


class Array(Func):
    arg_types = {"expressions": False}
    is_var_len_args = True


class ArrayAgg(AggFunc):
    pass


class ArrayContains(Func):
    arg_types = {"this": True, "expression": True}


class ArraySize(Func):
    pass


class Avg(AggFunc):
    pass


class Ceil(Func):
    _sql_names = ["CEIL", "CEILING"]


class Coalesce(Func):
    arg_types = {"this": True, "expressions": False}
    is_var_len_args = True


class Count(AggFunc):
    arg_types = {"this": False, "distinct": False}


class DateAdd(Func):
    arg_types = {"this": True, "expression": True, "unit": False}


class DateDiff(Func):
    arg_types = {"this": True, "expression": True, "unit": False}


class DateStrToDate(Func):
    pass


class Day(Func):
    pass


class Exp(Func):
    pass


class Floor(Func):
    pass


class Greatest(Func):
    arg_types = {"this": True, "expressions": True}
    is_var_len_args = True


class If(Func):
    arg_types = {"this": True, "true": True, "false": False}


class Initcap(Func):
    pass


class JSONPath(Func):
    arg_types = {"this": True, "path": True}
    _sql_names = ["JSON_PATH"]


class Least(Func):
    arg_types = {"this": True, "expressions": True}
    is_var_len_args = True


class Ln(Func):
    pass


class Log10(Func):
    pass


class Map(Func):
    arg_types = {"keys": True, "values": True}


class Max(AggFunc):
    pass


class Min(AggFunc):
    pass


class Month(Func):
    pass


class Pow(Func):
    arg_types = {"this": True, "power": True}
    _sql_names = ["POW", "POWER"]


class Quantile(AggFunc):
    arg_types = {"this": True, "quantile": True}


class RegexLike(Func):
    arg_types = {"this": True, "expression": True}


class Round(Func):
    arg_types = {"this": True, "decimals": False}


class StrPosition(Func):
    arg_types = {"this": True, "substr": True, "position": False}


class StrToTime(Func):
    arg_types = {"this": True, "format": True}


class StrToUnix(Func):
    arg_types = {"this": True, "format": True}


class StructExtract(Func):
    arg_types = {"this": True, "expression": True}


class Sum(AggFunc):
    pass


class Sqrt(Func):
    pass


class Stddev(AggFunc):
    pass


class StddevPop(AggFunc):
    pass


class StddevSamp(AggFunc):
    pass


class TimeToStr(Func):
    arg_types = {"this": True, "format": True}


class TimeToTimeStr(Func):
    pass


class TimeToUnix(Func):
    pass


class TimeStrToDate(Func):
    pass


class TimeStrToTime(Func):
    pass


class TimeStrToUnix(Func):
    pass


class TsOrDsToDateStr(Func):
    pass


class TsOrDsToDate(Func):
    pass


class UnixToStr(Func):
    arg_types = {"this": True, "format": True}


class UnixToTime(Func):
    pass


class UnixToTimeStr(Func):
    pass


class Variance(AggFunc):
    pass


class VariancePop(AggFunc):
    pass


class VarianceSamp(AggFunc):
    pass


def _token_arg_text(expression, kind):
    arg = expression.args.get(kind)
    return arg.text if arg else None


def _all_functions():
    predicate = (
        lambda obj: inspect.isclass(obj)
        and issubclass(obj, Func)
        and obj not in (AggFunc, Anonymous, Func)
    )
    return [obj for _, obj in inspect.getmembers(sys.modules[__name__], predicate)]


ALL_FUNCTIONS = _all_functions()
