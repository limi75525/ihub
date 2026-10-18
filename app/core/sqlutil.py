"""SQL 查询辅助。

LIKE 通配符转义与前缀转义：
不转义时 q="%%%" 会退化成全表通配扫描（单 % 全表通配，大库全表扫描）。
"""


def escape_like(kw: str) -> str:
    """LIKE 通配符转义（% _ \\），配合 ilike(..., escape="\\\\") 使用。"""
    return kw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def like_prefix(prefix: str) -> str:
    """前缀转成安全的 LIKE 模式（前缀里的 % _ 按字面匹配），与 escape_like 同口径。"""
    return escape_like(prefix) + "%"
