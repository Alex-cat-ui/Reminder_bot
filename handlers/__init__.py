from aiogram import Router

from . import start, timezone, wizard, weekly, callbacks

router = Router()
router.include_router(start.router)
router.include_router(timezone.router)
router.include_router(wizard.router)
router.include_router(weekly.router)
router.include_router(callbacks.router)
