from aiogram import Router

from . import start, timezone, wizard, task_browser, event_edit, weekly, callbacks, metrics

router = Router()
router.include_router(start.router)
router.include_router(timezone.router)
router.include_router(wizard.router)
router.include_router(task_browser.router)
router.include_router(event_edit.router)
router.include_router(weekly.router)
router.include_router(callbacks.router)
router.include_router(metrics.router)
