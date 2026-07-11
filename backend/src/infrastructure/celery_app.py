"""
基础设施层 - Celery 应用配置
用于异步执行碳审计工作流。
"""

from celery import Celery

from config.settings import CELERY_BROKER_URL, CELERY_RESULT_BACKEND


def create_celery_app() -> Celery:
    """
    创建并配置 Celery 应用实例。

    Returns:
        配置好的 Celery 实例
    """
    celery_app = Celery(
        "carbon_audit",
        broker=CELERY_BROKER_URL,
        backend=CELERY_RESULT_BACKEND,
    )

    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="Asia/Shanghai",
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        worker_concurrency=2,
    )

    return celery_app


# 模块级单例
celery_app = create_celery_app()
