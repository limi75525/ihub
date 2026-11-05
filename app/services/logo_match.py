"""头像库匹配规则链（消息渠道无关）。

从 api/v1/messages.py 下沉：stats 总览、接入服务等非消息路由也要复用
同一套「号码/邮箱精确 → 签名精确 → 签名前缀 → 邮箱@域名」降级链与头像地址解析，
路由层互相 import 私有函数违反依赖方向。
"""

import json
import re

from sqlalchemy.orm import Session

from app.models.logo_group import LogoGroup
from app.models.logo_rule import LogoRule
from app.models.message import Message
from app.services.logo_urls import file_url

# 短信企业签名：【xxx】 / [xxx]
_SMS_SIGNATURE_RE = re.compile(r"^\s*[【\[]\s*([^】\]]{1,24}?)\s*[】\]]")

_EMAIL_IN_HEADER_RE = re.compile(r"<([^<>\s]+@[^<>\s]+)>")


def logo_rules(db: Session, user_id: int) -> tuple[list[LogoRule], dict[int, LogoGroup]]:
    """取用户全部有效匹配规则 + 其所属企业分组（按 id 索引）。"""
    rules = db.query(LogoRule).filter(LogoRule.user_id == user_id, LogoRule.is_deleted.is_(False)).all()
    groups = {
        g.id: g
        for g in db.query(LogoGroup).filter(LogoGroup.user_id == user_id, LogoGroup.is_deleted.is_(False)).all()
    }
    return rules, groups


def _norm_phone(v: str) -> str:
    return (v or "").replace(" ", "").replace("-", "").replace("+86", "")


def _loads_json(raw: str | None, default):
    """容忍脏数据：单条记录的 JSON 损坏不应让整个列表接口 500。"""
    try:
        value = json.loads(raw or "")
    except (ValueError, TypeError):
        return default
    return value if isinstance(value, type(default)) else default


def match_logo(rules: list[LogoRule], groups: dict[int, LogoGroup], m: Message) -> LogoRule | LogoGroup | None:
    """匹配降级链（渠道无关）：号码/邮箱精确 → 签名精确 → 签名前缀 → 邮箱@域名。

    - account：短信=号码（归一化），邮件=发件地址；
    - signature：短信=【】企业签名，邮件=显示名（尖括号前），通知=发方名称；
    - 签名两级中规则企业名优先，随后以分组名兜底（美团 分组天然命中 美团/美团外卖），
      前缀多命中取最长名称（更具体）。
    命中规则未设「精确头像」时由 avatar_logo 回退企业默认头像；命中分组即企业默认头像。"""
    if m.channel == "sms":
        account = _norm_phone(m.sender or "")
        sig_m = _SMS_SIGNATURE_RE.match(m.content_text or "")
        sig = sig_m.group(1).strip() if sig_m else ""
    elif m.channel == "email":
        extra = _loads_json(m.extra, {})
        account = (extra.get("sender_email") or "").strip().lower()
        sender = (m.sender or "").strip()
        if not account:
            # 兼容「昵称 <addr@dom.com>」形态：取尖括号内的地址
            angled = _EMAIL_IN_HEADER_RE.search(sender)
            account = (angled.group(1) if angled else sender).lower()
            if "@" not in account:
                account = ""
        # 显示名 = 尖括号前的部分（「京东健康 <x@jd.com>」→「京东健康」）
        angled = _EMAIL_IN_HEADER_RE.search(sender)
        if angled:
            sig = sender[: angled.start()].strip()
        elif "@" not in sender:
            sig = sender
        else:
            sig = ""
    else:  # api / notify：发方名称参与签名两级匹配
        account = ""
        sig = (m.sender or "").strip()

    if account:
        for r in rules:
            if r.account and r.account == account:
                return r
    if sig:
        for r in rules:
            if r.signature and r.signature == sig:
                return r
        # 签名前缀（规则）：京东 命中 京东外卖；多命中取最长企业名
        prefix_best: LogoRule | None = None
        for r in rules:
            if r.signature and len(r.signature) < len(sig) and sig.startswith(r.signature):
                if prefix_best is None or len(r.signature) > len(prefix_best.signature):
                    prefix_best = r
        if prefix_best is not None:
            return prefix_best
        # 分组名兜底：企业名本身也参与精确与前缀匹配（美团 → 美团外卖/美团优选）
        for g in groups.values():
            if g.name and g.name == sig:
                return g
        g_best: LogoGroup | None = None
        for g in groups.values():
            if g.name and len(g.name) < len(sig) and sig.startswith(g.name):
                if g_best is None or len(g.name) > len(g_best.name):
                    g_best = g
        if g_best is not None:
            return g_best
    # 邮箱@域名降级：完整地址未命中规则时命中同域名任一规则（team@jd.com → noreply@jd.com 的规则）
    if account and "@" in account:
        domain = account.rsplit("@", 1)[-1]
        if domain:
            for r in rules:
                if r.account and "@" in r.account and r.account.rsplit("@", 1)[-1] == domain:
                    return r
    return None


def avatar_logo(obj: LogoRule | LogoGroup | None, groups: dict[int, LogoGroup] | None = None) -> str | None:
    """命中规则 → 规则「精确头像」；未设置 → 企业默认头像；命中分组 → 企业默认头像。"""
    if obj is None:
        return None
    if isinstance(obj, LogoGroup):
        return file_url(obj.logo_path, f"/api/v1/logos/groups/{obj.id}/logo-file", obj.logo_url)
    if obj.logo_path or obj.logo_url:
        return file_url(obj.logo_path, f"/api/v1/logos/rules/{obj.id}/logo-file", obj.logo_url)
    g = (groups or {}).get(obj.group_id)
    if g is not None:
        return file_url(g.logo_path, f"/api/v1/logos/groups/{g.id}/logo-file", g.logo_url)
    return None
