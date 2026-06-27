"""
Celery-free task runner stub for deployment.
Provides the same .task() decorator and .delay() interface as Celery,
but runs everything synchronously in-process (same as ALWAYS_EAGER=True).
No celery, redis, or broker needed.
"""
import logging

logger = logging.getLogger(__name__)


class _SyncTask:
    """Wraps a function to provide a .delay() method that calls it directly."""
    def __init__(self, fn):
        self.fn = fn
        self.__name__ = fn.__name__
        self.__doc__ = fn.__doc__

    def delay(self, *args, **kwargs):
        """Run the task synchronously (no queue)."""
        logger.info(f"[SyncTask] Running task: {self.__name__}")
        return self.fn(*args, **kwargs)

    def __call__(self, *args, **kwargs):
        return self.fn(*args, **kwargs)


class _SyncCeleryApp:
    """Minimal Celery-compatible app that runs tasks synchronously."""

    def task(self, *args, name=None, **kwargs):
        """Decorator that wraps functions in _SyncTask."""
        if len(args) == 1 and callable(args[0]):
            # Called as @celery_app.task (no arguments)
            return _SyncTask(args[0])
        # Called as @celery_app.task(name=...) with arguments
        def decorator(fn):
            return _SyncTask(fn)
        return decorator

    def autodiscover_tasks(self, *args, **kwargs):
        pass  # No-op in sync mode


celery_app = _SyncCeleryApp()
