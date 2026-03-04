"""Canonical user-facing texts and preview formatter."""

from __future__ import annotations

from datetime import datetime

MSG_MAIN_MENU = "Главное меню:"
MSG_SET_TZ_FIRST = "Сначала установите часовой пояс: /tz"
MSG_BAD_TZ = "Некорректный timezone. Попробуйте снова."
MSG_TZ_SET = "Timezone установлен: {tz}"
MSG_TZ_CANCELLED = "Выбор часового пояса отменен."

MSG_CREATION_CANCELLED = "Создание напоминания отменено."
MSG_EDIT_CANCELLED = "Редактирование отменено."
MSG_CREATED = "Напоминание создано."
MSG_UPDATED = "Задача обновлена."
MSG_WHAT_TO_EDIT = "Что изменить?"
MSG_SELECT_EDIT_FIELD = "Выберите, что изменить:"

MSG_INVALID_ACTION = "Некорректное действие."
MSG_STALE_CALENDAR = "Календарь устарел. Начните заново."
MSG_INVALID_DATE = "Некорректная дата."
MSG_DEBOUNCE = "Слишком часто. Нажмите еще раз."
MSG_CALENDAR_UPDATED = "Календарь обновлен."
MSG_CALENDAR_UPDATE_ERROR = "Ошибка обновления календаря. Попробуйте снова."
MSG_UNAUTHORIZED = "Задача не найдена или недоступна."

MSG_ENTER_ACTIVITY = "Введите активность (1-200 символов):"
MSG_ACTIVITY_LEN = "Активность должна быть от 1 до 200 символов."
MSG_ENTER_NOTES = "Введите заметки (или '-' если без заметок). Перечисление через запятую станет списком:"
MSG_ENTER_TIME_MANUAL = "Введите время вручную (например: 18:00, вечером)."
MSG_ENTER_TIME_MANUAL_EDIT = "Введите новое время вручную (например: 18:00, вечером)."
MSG_PICK_DATE_WITH_BUTTONS = "Выберите дату кнопками календаря или нажмите 'Отмена'."
MSG_CONFIRM_FALLBACK = "Нажмите 'Подтвердить', 'Изменить' или 'Отмена'."
MSG_EDIT_MENU_FALLBACK = "Используйте кнопки 'Дата/время', 'Активность', 'Заметки' или 'Отмена'."
MSG_CALENDAR_STEP = "Шаг 1/4. Выберите дату в календаре."
MSG_TIME_STEP = "Шаг 2/4. Введите время (например: 18:00, вечером)."
MSG_EDIT_CALENDAR_STEP = "Шаг 1/2. Выберите новую дату в календаре."
MSG_EDIT_TIME_STEP = "Шаг 2/2. Введите новое время (например: 18:00, вечером)."
MSG_ENTER_NEW_ACTIVITY = "Введите новую активность (1-200 символов):"
MSG_ENTER_NEW_NOTES = "Введите новые заметки (или '-' если без заметок)."

MSG_TIME_PARSE_ERROR = "Не понял время. Попробуйте снова (например: 18:00, вечером)."
MSG_TIME_PAST = "Это время уже прошло для выбранной даты. Введите более позднее время."

MSG_WEEK_EMPTY = "На этой неделе нет активных напоминаний."
MSG_WEEK_EDIT_PROMPT = "Выберите, что изменить:"
MSG_BROWSER_CLOSED = "Список закрыт."
MSG_BROWSER_EMPTY = "Список пуст."
MSG_CLONE_CREATED = "Копия задачи создана."

MSG_SNOOZE_LIMIT = "Лимит откладываний достигнут (25)."
MSG_DONE = "✅ Завершено"
MSG_DELETED = "Удалено."
MSG_DELETED_WITH_UNDO = "Задача удалена."
MSG_UNDO_RESTORED = "Удаление отменено."
MSG_UNDO_EXPIRED = "Срок отмены удаления истек."
MSG_DUPLICATE_WARNING = "Похоже, такая задача уже есть на это время. Сохранить все равно?"


def format_event_preview(
    *,
    dt: datetime,
    activity: str,
    notes: str | None,
    tz_name: str,
    mode: str = "create",
) -> str:
    """Unified preview text with explicit timezone."""
    header = "Проверьте напоминание:" if mode == "create" else "Проверьте изменения:"
    dt_str = dt.strftime("%d.%m.%Y %H:%M")
    notes_str = notes or "—"
    return (
        f"{header}\n\n"
        f"Когда: {dt_str} ({tz_name})\n"
        f"Активность: {activity}\n"
        f"Заметки:\n{notes_str}"
    )
