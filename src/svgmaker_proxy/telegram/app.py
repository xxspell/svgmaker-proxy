from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from svgmaker_proxy.api.app import initialize_services
from svgmaker_proxy.bootstrap import ServiceContainer, build_services
from svgmaker_proxy.core.config import get_settings
from svgmaker_proxy.core.logging import configure_logging
from svgmaker_proxy.telegram.service import TelegramBotError, TelegramBotService

logger = logging.getLogger(__name__)


class PromptStates(StatesGroup):
    waiting_for_prompt = State()


def build_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Сгенерировать", callback_data="generate")
    builder.adjust(1)
    return builder.as_markup()


def build_bot_service(services: ServiceContainer) -> TelegramBotService:
    return TelegramBotService(
        telegram_user_repository=services.telegram_user_repository,
        telegram_invite_code_repository=services.telegram_invite_code_repository,
        generation_proxy=services.generation_proxy,
    )


async def configure_dispatcher(dp: Dispatcher, bot_service: TelegramBotService) -> None:
    @dp.message(CommandStart(deep_link=True))
    @dp.message(CommandStart())
    async def start_handler(message: Message, state: FSMContext) -> None:
        command = message.text or "/start"
        parts = command.split(maxsplit=1)
        start_code = parts[1].strip() if len(parts) > 1 else None
        user, invite = await bot_service.register_or_get_user(message.from_user, start_code)
        decision = await bot_service.get_quota_decision(user.telegram_user_id)
        await state.clear()

        lines = [f"Привет, {decision.user.display_name}!"]
        if invite is not None and decision.user.is_unlimited:
            lines.append("У вас есть безлимитный доступ к генерации.")
        elif decision.user.is_unlimited:
            lines.append("У вас есть безлимитный доступ к генерации.")
        else:
            lines.append(f"Сейчас у вас доступно генераций: {decision.user.quota_remaining}.")
            lines.append(
                "При первом запуске даётся 3 генерации. "
                "Когда баланс станет 0, на следующий день начислится 1 новая генерация."
            )
            if decision.user.quota_remaining <= 0:
                lines.append("Сейчас кнопка генерации недоступна. Приходите завтра.")

        reply_markup = None
        if decision.user.is_unlimited or decision.user.quota_remaining > 0:
            reply_markup = build_menu_keyboard()
        await message.answer("\n".join(lines), reply_markup=reply_markup)

    @dp.callback_query(F.data == "generate")
    async def generate_callback(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        decision = await bot_service.get_quota_decision(callback.from_user.id)
        if not decision.is_unlimited and decision.quota_remaining <= 0:
            await state.clear()
            if callback.message is not None:
                await callback.message.answer(
                    "Сейчас бесплатных генераций нет. Приходите завтра за следующей."
                )
            return
        await state.set_state(PromptStates.waiting_for_prompt)
        if callback.message is not None:
            await callback.message.answer("Отправьте промпт для генерации изображения.")

    @dp.message(PromptStates.waiting_for_prompt)
    async def prompt_handler(message: Message, state: FSMContext) -> None:
        prompt = (message.text or "").strip()
        if not prompt:
            await message.answer("Пожалуйста, отправьте непустой промпт.")
            return

        wait_message = await message.answer("Генерирую изображение...")
        try:
            result = await bot_service.generate_for_user(message.from_user.id, prompt)
        except TelegramBotError as exc:
            await wait_message.edit_text(str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("Telegram generation failed for user_id=%s", message.from_user.id)
            await wait_message.edit_text(f"Ошибка генерации: {exc}")
            return
        finally:
            await state.clear()

        caption = bot_service.format_result_caption(result)
        if result.photo_bytes and result.photo_filename:
            await message.answer_photo(
                BufferedInputFile(result.photo_bytes, filename=result.photo_filename),
                caption=caption,
            )
        elif result.svg_bytes and result.svg_filename:
            await message.answer_document(
                BufferedInputFile(result.svg_bytes, filename=result.svg_filename),
                caption=caption,
            )
        else:
            await message.answer(caption)

        if result.svg_bytes and result.svg_filename:
            await message.answer_document(
                BufferedInputFile(result.svg_bytes, filename=result.svg_filename),
                caption="Исходный SVG-файл",
            )

        if result.is_unlimited or (result.remaining_generations or 0) > 0:
            await message.answer(
                "Если хотите, можете сразу сгенерировать ещё одну.",
                reply_markup=build_menu_keyboard(),
            )
        else:
            await message.answer(
                "Бесплатные генерации на сегодня закончились. Приходите завтра."
            )
        await wait_message.delete()


async def run_bot(services: ServiceContainer | None = None, initialize: bool = True) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN must be configured")

    configure_logging(settings.log_level)
    container = services or build_services()
    if initialize:
        await initialize_services(container)

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    await configure_dispatcher(dp, build_bot_service(container))

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        if initialize:
            await container.database.dispose()


def main() -> None:
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
