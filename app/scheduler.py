"""APScheduler 调度管理：为每个启用的邮箱来源维护一个轮询任务。"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.services.imap_service import poll_source
from app.services.purge import purge_expired
from app.services.retention import check_pending, run_retention_cleanup

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="UTC", job_defaults={"coalesce": True, "max_instances": 1})


def sync_email_jobs(sources: list) -> None:
    """根据来源列表同步任务（增/删/改间隔）。sources 必须是全量表中的来源对象
    （含 id/type/poll_interval/is_active）——按用户过滤会导致其他用户的轮询任务被误删。"""
    wanted = {}
    for s in sources:
        if s.type == "email" and s.is_active:
            wanted[f"email_poll_{s.id}"] = s.poll_interval

    # 只回收本函数管辖的邮箱轮询任务；retention/purge 等维护任务不在此列
    existing = {
        job.id for job in scheduler.get_jobs() if str(job.id).startswith("email_poll_")
    }
    for job_id, interval in wanted.items():
        job = scheduler.get_job(job_id)
        if job is None:
            scheduler.add_job(
                poll_source,
                IntervalTrigger(seconds=interval),
                id=job_id,
                args=[int(job_id.removeprefix("email_poll_"))],
                replace_existing=True,
            )
            logger.info("已添加邮箱轮询任务 %s（每 %ss）", job_id, interval)
        elif job.trigger.interval.total_seconds() != interval:
            job.reschedule(IntervalTrigger(seconds=interval))
            logger.info("已调整任务 %s 间隔为 %ss", job_id, interval)

    for job_id in existing - set(wanted):
        scheduler.remove_job(job_id)
        logger.info("已移除任务 %s", job_id)


def register_retention_job() -> None:
    """每日清理一次超过保留期的历史消息（UTC 18:30 = 北京时间 02:30）。"""
    scheduler.add_job(
        run_retention_cleanup,
        CronTrigger(hour=18, minute=30),
        id="retention_cleanup",
        replace_existing=True,
    )
    # 每分钟检查“短期化 10 分钟后删除”的待执行任务
    scheduler.add_job(
        check_pending,
        IntervalTrigger(seconds=60),
        id="retention_pending_check",
        replace_existing=True,
    )


def register_janitor_job() -> None:
    """每日缓存/孤儿文件清理（UTC 19:40 = 北京时间 03:40，与 retention 错峰）。"""
    from app.services.janitor import run_janitor

    scheduler.add_job(
        run_janitor,
        CronTrigger(hour=19, minute=40),
        id="cache_janitor",
        replace_existing=True,
    )


def register_update_check_job() -> None:
    """每日检查一次 iHub 新版本（GitHub Release），有新版通知管理员（每版本只提醒一次）。"""
    from app.services.notify_service import background_notify_admins

    def _check() -> None:
        import json as jsonlib
        import re as _re

        from app.core import outbound
        from app.core.config import settings as cfg

        try:
            url = "https://api.github.com/repos/limi75525/ihub/releases/latest"
            req = outbound.urllib.request.Request(url, headers={"User-Agent": "iHub/1.0", "Accept": "application/json"})
            with outbound.opener_for(url).open(req, timeout=15) as resp:
                data = jsonlib.loads(resp.read(1_000_000))
            tag = str(data.get("tag_name") or "").lstrip("vV")
            if not _re.match(r"^\d+(\.\d+)*$", tag):
                return
            local = [int(x) for x in _re.match(r"^(\d+(?:\.\d+)*)", cfg.APP_VERSION).group(1).split(".")]
            remote = [int(x) for x in tag.split(".")]
            if remote <= local:
                return
            body = f"检测到新版本 v{tag}（当前 v{cfg.APP_VERSION}），请到 GitHub Releases 查看更新内容。"
            background_notify_admins(
                type="update",
                title="iHub 有新版本",
                body=body,
                link="#/settings?tab=about",
                dedup_key=f"update:{tag}",
            )
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug("版本更新检查失败：%s", e)

    scheduler.add_job(
        _check,
        CronTrigger(hour=21, minute=0),
        id="update_check",
        replace_existing=True,
    )


def register_purge_job() -> None:
    """每日物理清理到期（默认 30 天）的逻辑删除数据（UTC 04:00 = 北京时间 12:00）。"""
    scheduler.add_job(
        purge_expired,
        CronTrigger(hour=4, minute=0),
        id="soft_delete_purge",
        replace_existing=True,
    )
