"""IMAP 增量拉取与解析。使用 UID 游标 + UIDVALIDITY 防重复，只读方式连接不改邮箱状态。

解析要点：
- 内嵌图片（<img src="cid:...">）转 data URI 内联，保证正文图片可显示；
- 提取发件人邮箱地址（供前端展示 Gravatar 头像）；
- 仅带文件名的部件视为附件（内嵌图不进附件列表）。
"""

import base64
import email
import hashlib
import imaplib
import logging
import re
import ssl
from datetime import datetime, timezone
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.message import Message
from app.models.source import Source
from app.services.ingest_service import create_message, save_attachments

logger = logging.getLogger(__name__)

MAX_FIRST_SYNC = 30  # 首次同步最多拉取的最新邮件数
MAX_INLINE_IMAGE = 1 * 1024 * 1024  # 超过该大小的内嵌图片不内联（避免撑爆正文）
MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024  # 单附件上限：超限不落盘，正文加提示（防磁盘被单封邮件灌满）
MAX_TEXT_PART = 5 * 1024 * 1024  # 单文本部件解码上限（防异常超大部件撑爆内存）

# 最近一次拉取的失败原因（进程内存）：poll_source 以「返回条数」为契约，
# 失败与「没有新邮件」都返回 0，接口层由此区分为用户可见的错误提示。
_last_errors: dict[int, str] = {}


def last_error(source_id: int) -> str | None:
    return _last_errors.get(source_id)


def _decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    try:
        parts = decode_header(value)
        decoded = []
        for data, charset in parts:
            if isinstance(data, bytes):
                decoded.append(data.decode(charset or "utf-8", errors="replace"))
            else:
                decoded.append(data)
        return "".join(decoded)
    except Exception:
        return value or ""


def _parse_date(msg) -> datetime:
    raw = msg.get("Date")
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _img_to_data_uri(data: bytes, ctype: str) -> str:
    return f"data:{ctype};base64,{base64.b64encode(data).decode('ascii')}"


def _ssl_context(verify_tls: bool) -> ssl.SSLContext:
    """IMAP SSL 连接的证书校验策略。

    默认校验服务端证书（imaplib.IMAP4_SSL 不传 ssl_context 时用的是
    CERT_NONE 的 stdlib 上下文——只有加密没有身份认证，中间人可截获授权码）。
    verify_tls=False 仅用于自签证书的私有邮件服务器，由用户在来源里显式关闭。
    """
    ctx = ssl.create_default_context()
    if not verify_tls:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _decode_part(payload: bytes, charset: str | None) -> str:
    """按邮件声明的 charset 解码正文部件。

    charset 来自攻击者可控的邮件头：声明一个不存在的编码名时 bytes.decode
    抛 LookupError（errors="replace" 只兜解码错误，不兜未知编码名），
    未捕获会让整封邮件解析失败、拉取游标永不推进，该来源从此收不进新邮件。
    """
    try:
        return payload[:MAX_TEXT_PART].decode(charset or "utf-8", errors="replace")
    except (LookupError, UnicodeError):
        return payload[:MAX_TEXT_PART].decode("utf-8", errors="replace")


def _safe_folder(folder: str | None) -> str:
    """IMAP 文件夹名只作为 select 参数使用；imaplib 不做 CRLF 转义，
    恶意/误填的换行会拼进协议命令行（命令注入），这里直接剥掉控制字符。"""
    name = (folder or "").strip()
    if not name or re.search(r"[\r\n\x00]", name):
        return "INBOX"
    return name[:512]


def parse_email(raw_bytes: bytes) -> dict:
    """解析原始邮件 → {sender, sender_email, recipient, title, text, html, date, attachments}"""
    msg = email.message_from_bytes(raw_bytes)

    from_name, from_addr = parseaddr(_decode_header_value(msg.get("From", "")))
    to_header = _decode_header_value(msg.get("To", "")).strip()
    cc_header = _decode_header_value(msg.get("Cc", "")).strip()
    to_name, to_addr = parseaddr(to_header)

    text, html = "", ""
    attachments: list[dict] = []
    inline_images: list[tuple[str, str, bytes]] = []  # (content_id, content_type, data)

    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        filename = part.get_filename()
        disposition = (part.get("Content-Disposition") or "").lower()
        content_id = (part.get("Content-ID") or "").strip().strip("<>")

        payload = part.get_payload(decode=True) or b""

        if content_id and ctype.startswith("image/"):
            inline_images.append((content_id, ctype, payload))
            continue
        if filename or "attachment" in disposition:
            att_name = _decode_header_value(filename) or "unnamed"
            if len(payload) > MAX_ATTACHMENT_SIZE:
                # 超限附件不落盘：磁盘与内存保护优先（正文里给出可见提示）
                text += (
                    f"\n\n[附件 {att_name} 超过 "
                    f"{MAX_ATTACHMENT_SIZE // 1024 // 1024}MB，未保存]"
                )
                continue
            attachments.append(
                {
                    "filename": att_name,
                    "data": payload,
                    "content_type": ctype,
                }
            )
        elif ctype == "text/plain" and not text:
            text = _decode_part(payload, part.get_content_charset())
        elif ctype == "text/html" and not html:
            html = _decode_part(payload, part.get_content_charset())

    # 内嵌图片：cid 引用 → data URI（含引号包裹的 src="cid:xxx" 场景）
    for cid, ctype, data in inline_images:
        if len(data) <= MAX_INLINE_IMAGE:
            html = html.replace(f"cid:{cid}", _img_to_data_uri(data, ctype))
            html = html.replace(f"CID:{cid}", _img_to_data_uri(data, ctype))

    # 清洗未匹配到内嵌图部件（缺失/超大/跨邮件）的残留 cid 引用，
    # 避免浏览器加载 cid: 地址报错并显示破图
    if "cid:" in html.lower():
        html = re.sub(r"<img\b[^>]*?src=\"cid:[^\"]*\"[^>]*?>", "", html, flags=re.IGNORECASE)
        html = re.sub(r"<img\b[^>]*?src='cid:[^']*'[^>]*?>", "", html, flags=re.IGNORECASE)
        html = re.sub(r'cid:[^\s"\'>]+', "", html, flags=re.IGNORECASE)

    title = _decode_header_value(msg.get("Subject", ""))
    message_id = (msg.get("Message-ID") or "").strip()
    date = _parse_date(msg)

    return {
        "sender": from_name or from_addr,
        "sender_email": from_addr,
        # 收件人保留解码后的完整头（可能多人），空 To（密送类邮件）则为空串
        "recipient": to_header or to_addr,
        "cc": cc_header,
        "title": title or "(无主题)",
        "text": text,
        "html": html if html != text else "",
        "date": date,
        "attachments": attachments,
        "message_id": message_id,
    }


def _email_dedup_key(parsed: dict) -> str:
    """Message-ID 优先；缺失时用 发件人|主题|日期 兜底。"""
    key_material = parsed["message_id"] or (
        f"{parsed['sender']}|{parsed['title']}|{parsed['date'].isoformat()}"
    )
    return hashlib.sha256(key_material.encode("utf-8")).hexdigest()


def test_connection(
    host: str,
    port: int,
    use_ssl: bool,
    account: str,
    password: str,
    folder: str = "INBOX",
    verify_tls: bool = True,
) -> tuple[bool, str]:
    try:
        if use_ssl:
            conn = imaplib.IMAP4_SSL(
                host, port, ssl_context=_ssl_context(verify_tls), timeout=15
            )
        else:
            conn = imaplib.IMAP4(host, port, timeout=15)
        try:
            conn.login(account, password)
            folder = _safe_folder(folder)
            status, _ = conn.select(folder, readonly=True)
            if status != "OK":
                return False, f"无法打开文件夹 {folder}"
            return True, "连接成功"
        finally:
            try:
                conn.logout()
            except Exception:
                pass
    except imaplib.IMAP4.error as e:
        return False, f"认证失败：{e}（请检查账号与授权码）"
    except ssl.SSLCertVerificationError:
        return False, "SSL 证书校验失败（自签证书的邮件服务器可在来源设置中关闭「校验 SSL 证书」）"
    except (OSError, ValueError, OverflowError) as e:
        # ValueError/OverflowError：非法主机名（含 \x00）或超范围端口，getaddrinfo 直接抛出
        return False, f"连接失败：{e}（请检查服务器地址与端口）"


def _update_existing_email(db: Session, existing: Message, parsed: dict, uid: int) -> None:
    """同 ID 邮件重新拉取时刷新解析结果（正文图片内联等修复随重拉生效）。"""
    import json
    import shutil
    from pathlib import Path

    from app.core.config import settings

    att_dir = Path(settings.DATA_DIR) / "attachments" / str(existing.source_id) / existing.dedup_hash[:16]
    if att_dir.is_dir():
        shutil.rmtree(att_dir, ignore_errors=True)

    saved = save_attachments(existing.source_id, existing.dedup_hash, parsed["attachments"])
    existing.sender = (parsed["sender"] or "")[:256]
    existing.recipient = (parsed["recipient"] or "")[:256]
    existing.title = (parsed["title"] or "")[:512]
    existing.content_text = parsed["text"]
    existing.content_html = parsed["html"] or None
    existing.attachments = json.dumps(saved, ensure_ascii=False)
    extra = json.loads(existing.extra or "{}")
    extra.update({"message_id": parsed["message_id"], "uid": uid, "sender_email": parsed["sender_email"]})
    existing.extra = json.dumps(extra, ensure_ascii=False)
    db.add(existing)


def poll_source(source_id: int, limit: int | None = None) -> int:
    """拉取单个邮箱来源的新邮件，返回新增/更新条数。由调度器在线程池中调用。

    limit：单次只取最新的 limit 封（手动拉取/重新解析用）；None 不限制（定时轮询），
    避免定时增量拉取跳过中间邮件。
    """
    db: Session = SessionLocal()
    fetched = 0
    conn = None
    _last_errors.pop(source_id, None)
    try:
        source = db.get(Source, source_id)
        if not source or source.type != "email" or not source.is_active:
            return 0

        # 先解出授权码（密文解不开就直接返回，不必去连服务器），再建连接
        # 授权码为 Fernet 密文；历史明文（解密失败）原样回退，由启动迁移负责加密
        from app.core.crypto import decrypt_text, looks_encrypted

        password = decrypt_text(source.email_password) if source.email_password else None
        if password is None:
            if looks_encrypted(source.email_password or ""):
                # 密文解不开（SECRET_KEY 变更或还原了旧数据）：把密文当密码提交会连续触发
                # 邮箱端认证失败（可能被服务商风控），此处直接报错并跳过本轮拉取。
                logger.error(
                    "来源 %s（%s）邮箱授权码无法解密，请重新保存授权码",
                    source.name, source.email_account,
                )
                _last_errors[source_id] = "邮箱授权码无法解密，请在设置中重新保存授权码"
                return 0
            password = source.email_password

        if source.imap_ssl:
            # 老库行经轻量迁移补列后为 1（BOOLEAN DEFAULT 1）；None 视为开启校验
            conn = imaplib.IMAP4_SSL(
                source.imap_host,
                source.imap_port,
                ssl_context=_ssl_context(source.imap_verify_tls is not False),
                timeout=30,
            )
        else:
            conn = imaplib.IMAP4(source.imap_host, source.imap_port, timeout=30)
        conn.login(source.email_account, password)
        folder_name = _safe_folder(source.folder)
        status, _ = conn.select(folder_name, readonly=True)
        if status != "OK":
            logger.warning("来源 %s 无法打开文件夹 %s", source.name, folder_name)
            _last_errors[source_id] = f"无法打开邮箱文件夹 {folder_name}"
            return 0

        _, resp = conn.response("UIDVALIDITY")
        uidvalidity = int(resp[0]) if resp and resp[0] else 0
        if uidvalidity and uidvalidity != source.uidvalidity:
            logger.info(
                "来源 %s UIDVALIDITY 变化 %s→%s，重置游标",
                source.name, source.uidvalidity, uidvalidity,
            )
            source.uidvalidity = uidvalidity
            source.last_uid = 0

        search_since = source.last_uid + 1
        _, uid_list = conn.uid("search", None, f"UID {search_since}:*")
        uids = sorted(int(u) for u in (uid_list[0] or b"").split())
        uids = [u for u in uids if u > source.last_uid]
        if not uids:
            source.last_poll_at = datetime.now(timezone.utc)
            db.commit()
            return 0
        if limit:
            uids = uids[-limit:]
        elif source.last_uid == 0:
            uids = uids[-MAX_FIRST_SYNC:]

        for uid in uids:
            _, msg_data = conn.uid("fetch", str(uid), "(RFC822)")
            if not msg_data or msg_data[0] is None:
                continue
            raw = msg_data[0][1]
            parsed = parse_email(raw)
            dedup = _email_dedup_key(parsed)

            existing = (
                db.query(Message)
                .filter(Message.source_id == source.id, Message.dedup_hash == dedup)
                .first()
            )
            if existing:
                # 重拉场景（reparse）：刷新内容
                _update_existing_email(db, existing, parsed, uid)
                fetched += 1
            else:
                create_message(
                    db,
                    source,
                    channel="email",
                    sender=parsed["sender"],
                    recipient=parsed["recipient"],
                    title=parsed["title"],
                    content_text=parsed["text"],
                    content_html=parsed["html"] or None,
                    received_at=parsed["date"],
                    extra={
                        "message_id": parsed["message_id"],
                        "uid": uid,
                        "sender_email": parsed["sender_email"],
                        "cc": parsed["cc"],
                    },
                    attachments=parsed["attachments"],
                    dedup_hash=dedup,
                )
                fetched += 1
            source.last_uid = uid

        source.last_poll_at = datetime.now(timezone.utc)
        db.commit()
        return fetched
    except Exception as e:
        db.rollback()
        logger.exception("邮箱来源 %s 拉取失败", source_id)
        _last_errors[source_id] = str(e) or e.__class__.__name__
        return 0  # 契约：失败一律返回 0（已逐封 commit 的消息仍在，下轮按 dedup 幂等补齐游标）
    finally:
        db.close()
        if conn:
            try:
                conn.logout()
            except Exception:
                pass
