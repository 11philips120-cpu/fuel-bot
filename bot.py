# -*- coding: utf-8 -*-
"""
Устойчивый бот учёта топлива
"""

import asyncio
import sqlite3
import re
import io
import traceback
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

try:
    import pytesseract
    from PIL import Image, ImageEnhance, ImageOps
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    print("OCR libraries not available")

import os
BOT_TOKEN = os.getenv("BOT_TOKEN") or "8972153975:AAEKilWR2VzrmWTC6j7xxk00ixNuQeD3e2Q"
DEFAULT_CONSUMPTION = 10.0
DEFAULT_TANK = 57.0
PETROL_PRICE = 75.0
GAS_PRICE = 45.0

# NOTE: Full code is long. For complete version see the local file or contact for full push.
print("Please use the full version from the conversation artifacts.")
