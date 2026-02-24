#!/usr/bin/env python3
import os
import sys
import random
import time
from collections import defaultdict

import telebot
from telebot.types import Message

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    print("❌ Ошибка: переменная BOT_TOKEN не установлена!")
    sys.exit(1)

ADMIN_IDS = [int(x.strip()) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip()]
# ================================

bot = telebot.TeleBot(BOT_TOKEN)

games = {}

# Роли и их команды
ROLES = [
    "Мирный",      # ничего не делает
    "Геоинтер",    # узнаёт геолокацию (роль) цели
    "Доксер",      # может защитить игрока от убийства
    "Осинтер",     # собирает информацию (узнаёт, кто голосовал за цель)
    "Ксинтер",     # взламывает цель (узнаёт её роль)
    "Хуминтер",    # проверяет, атакована ли цель
    "Сватер",      # блокирует действие цели ночью
    "Хакер",       # может участвовать в убийстве (часть мафии)
    "Ддосер",      # может убить цель (часть мафии)
    "Досер",       # может убить цель (часть мафии)
]

MAFIA_ROLES = ["Ддосер", "Досер", "Хакер"]

class MafiaGame:
    def __init__(self, chat_id, creator_id):
        self.chat_id = chat_id
        self.creator_id = creator_id
        self.players = {}           # user_id -> username
        self.roles = {}             # user_id -> role
        self.alive = []             # живые user_id
        self.phase = "waiting"      # waiting, night, day, voting
        self.day_num = 1
        self.night_actions = {}     # user_id -> target_id
        self.protected = set()      # кто защищён в эту ночь (доксер)
        self.blocked = set()        # у кого заблокировано действие (сватер)
        self.votes = defaultdict(int)  # голоса за исключение
        self.night_results = []      # сообщения для утра

    def add_player(self, user_id, username):
        if user_id not in self.players and len(self.players) < len(ROLES):
            self.players[user_id] = username
            return True
        return False

    def start_game(self):
        if len(self.players) < 4:
            return False
        shuffled = list(self.players.keys())
        random.shuffle(shuffled)
        roles = random.sample(ROLES, k=len(shuffled))
        for uid, role in zip(shuffled, roles):
            self.roles[uid] = role
            self.alive.append(uid)
        self.phase = "night"
        self.day_num = 1
        return True

    def get_role(self, user_id):
        return self.roles.get(user_id, "Неизвестно")

    def is_alive(self, user_id):
        return user_id in self.alive

    def kill(self, user_id):
        if user_id in self.alive:
            self.alive.remove(user_id)

    def night_action(self, user_id, target_id):
        # Проверка: жив ли, может ли действовать
        if user_id not in self.alive or target_id not in self.alive:
            return False
        role = self.roles[user_id]
        # Если роль не может действовать (Мирный), то нельзя
        if role == "Мирный":
            return False
        # Уже действовал?
        if user_id in self.night_actions:
            return False
        self.night_actions[user_id] = target_id
        return True

    def resolve_night(self):
        results = []
        protected_this_night = set()
        blocked_this_night = set()
        kill_votes = defaultdict(int)  # голоса убийц

        # Сначала обрабатываем блокировку (сватер)
        for uid, tid in self.night_actions.items():
            if self.roles[uid] == "Сватер":
                blocked_this_night.add(tid)

        # Затем защиту (доксер)
        for uid, tid in self.night_actions.items():
            if self.roles[uid] == "Доксер" and tid not in blocked_this_night:
                protected_this_night.add(tid)

        # Теперь убийцы (ддосер, досер, хакер) – голосуют за цель
        for uid, tid in self.night_actions.items():
            if self.roles[uid] in MAFIA_ROLES and uid not in blocked_this_night:
                kill_votes[tid] += 1

        # Если есть голоса убийц, выбираем цель
        if kill_votes:
            max_votes = max(kill_votes.values())
            candidates = [tid for tid, v in kill_votes.items() if v == max_votes]
            target = random.choice(candidates)
            if target not in protected_this_night:
                self.kill(target)
                results.append(f"🔪 Убит {self.players[target]} (жертва мафии)")

        # Информационные роли – собираем сообщения для утра
        info_messages = []
        for uid, tid in self.night_actions.items():
            role = self.roles[uid]
            if role in MAFIA_ROLES or role in ["Доксер", "Сватер"]:
                continue  # уже учли
            if uid in blocked_this_night:
                info_messages.append(f"❌ {self.players[uid]} (роль {role}) заблокирован и ничего не узнал.")
                continue

            if role == "Геоинтер":
                info_messages.append(f"🌍 {self.players[uid]} узнал, что {self.players[tid]} — {self.roles[tid]}")
            elif role == "Осинтер":
                # Узнаёт, сколько голосов было за цель в предыдущий день
                prev_votes = self.votes.get(tid, 0)
                info_messages.append(f"📊 {self.players[uid]} выяснил, что за {self.players[tid]} голосовало {prev_votes} человек(а).")
            elif role == "Ксинтер":
                info_messages.append(f"💻 {self.players[uid]} взломал {self.players[tid]}, его роль — {self.roles[tid]}")
            elif role == "Хуминтер":
                if tid in kill_votes:
                    info_messages.append(f"🔎 {self.players[uid]} обнаружил, что {self.players[tid]} был целью атаки.")
                else:
                    info_messages.append(f"🔎 {self.players[uid]} не заметил подозрительной активности вокруг {self.players[tid]}.")
            elif role == "Хакер":
                # Хакер уже учтён в убийцах
                pass

        # Очищаем ночные данные
        self.night_actions.clear()
        self.protected = protected_this_night
        self.blocked = blocked_this_night
        self.night_results = results + info_messages
        return self.night_results

    def vote(self, user_id, target_id):
        if user_id in self.alive and target_id in self.alive:
            self.votes[target_id] += 1
            return True
        return False

    def resolve_voting(self):
        max_votes = max(self.votes.values()) if self.votes else 0
        if max_votes == 0:
            return None
        candidates = [uid for uid, v in self.votes.items() if v == max_votes]
        if len(candidates) == 1:
            return candidates[0]
        return None

    def next_phase(self):
        if self.phase == "night":
            results = self.resolve_night()
            self.phase = "day"
            self.day_num += 1
            return "day", results
        elif self.phase == "day":
            self.phase = "voting"
            self.votes.clear()
            return "voting", []
        elif self.phase == "voting":
            exiled = self.resolve_voting()
            if exiled:
                self.kill(exiled)
                self.phase = "night"
                return "exiled", exiled
            else:
                self.phase = "night"
                return "no_exile", None
        return self.phase, []

    def check_win(self):
        alive_roles = [self.roles[uid] for uid in self.alive]
        mafia_count = sum(1 for r in alive_roles if r in MAFIA_ROLES)
        civilians_count = len(self.alive) - mafia_count
        if mafia_count == 0:
            return "Мирные"
        if mafia_count >= civilians_count:
            return "Мафия"
        return None

# ========== КОМАНДЫ ==========
@bot.message_handler(commands=['start'])
def start_cmd(message: Message):
    bot.reply_to(message,
        "🎮 **Mafia Hack**\n\n"
        "Команды:\n"
        "/newgame — создать новую игру\n"
        "/join — присоединиться\n"
        "/startgame — начать игру (только создатель)\n"
        "/role — показать свою роль\n"
        "/action <id цели> — ночное действие\n"
        "/vote <id цели> — голосовать днём\n"
        "/status — статус игры\n"
        "/players — список игроков с ID\n"
        "/nextphase — перейти к следующей фазе (только создатель)",
        parse_mode='Markdown')

@bot.message_handler(commands=['newgame'])
def newgame(message: Message):
    chat_id = message.chat.id
    if chat_id in games:
        bot.reply_to(message, "❌ В этом чате уже есть игра. Используйте /join или дождитесь завершения.")
        return
    games[chat_id] = MafiaGame(chat_id, message.from_user.id)
    bot.reply_to(message, f"✅ Новая игра создана! Присоединяйтесь: /join\nКоличество игроков: 0")

@bot.message_handler(commands=['join'])
def join_game(message: Message):
    chat_id = message.chat.id
    game = games.get(chat_id)
    if not game:
        bot.reply_to(message, "❌ Игра не создана. Сначала /newgame")
        return
    if game.phase != "waiting":
        bot.reply_to(message, "❌ Игра уже началась, присоединиться нельзя.")
        return
    uid = message.from_user.id
    name = message.from_user.username or message.from_user.first_name or str(uid)
    if game.add_player(uid, name):
        bot.reply_to(message, f"✅ {name} присоединился. Всего игроков: {len(game.players)}")
    else:
        bot.reply_to(message, "❌ Не удалось присоединиться (возможно, уже в игре или максимум игроков).")

@bot.message_handler(commands=['startgame'])
def start_game(message: Message):
    chat_id = message.chat.id
    game = games.get(chat_id)
    if not game:
        bot.reply_to(message, "❌ Игра не создана.")
        return
    if message.from_user.id != game.creator_id:
        bot.reply_to(message, "❌ Только создатель игры может её начать.")
        return
    if game.phase != "waiting":
        bot.reply_to(message, "❌ Игра уже начата.")
        return
    if game.start_game():
        for uid in game.players:
            role = game.get_role(uid)
            try:
                bot.send_message(uid, f"🤫 Твоя роль: **{role}**\nДействуй в ночи командой /action <id цели> в общем чате.", parse_mode='Markdown')
            except:
                pass
        bot.send_message(chat_id, f"🎲 Игра началась! Ночь {game.day_num}. Приватные роли разосланы.\nИгроки: {', '.join(game.players.values())}")
        game.phase = "night"
    else:
        bot.reply_to(message, "❌ Недостаточно игроков (минимум 4).")

@bot.message_handler(commands=['players'])
def list_players(message: Message):
    chat_id = message.chat.id
    game = games.get(chat_id)
    if not game:
        bot.reply_to(message, "❌ Нет активной игры.")
        return
    text = "👥 **Игроки:**\n"
    for uid, name in game.players.items():
        alive = "🔴" if game.is_alive(uid) else "💀"
        text += f"{alive} {name} (ID: `{uid}`)\n"
    bot.reply_to(message, text, parse_mode='Markdown')

@bot.message_handler(commands=['role'])
def role(message: Message):
    chat_id = message.chat.id
    game = games.get(chat_id)
    if not game or game.phase == "waiting":
        bot.reply_to(message, "❌ Игра ещё не началась.")
        return
    uid = message.from_user.id
    role = game.get_role(uid)
    bot.reply_to(message, f"🕵️ Твоя роль: **{role}**", parse_mode='Markdown')

@bot.message_handler(commands=['action'])
def action(message: Message):
    chat_id = message.chat.id
    game = games.get(chat_id)
    if not game or game.phase != "night":
        bot.reply_to(message, "❌ Сейчас не ночь.")
        return
    uid = message.from_user.id
    if not game.is_alive(uid):
        bot.reply_to(message, "❌ Ты мёртв и не можешь действовать.")
        return
    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "❌ Использование: /action <id цели>")
        return
    try:
        target = int(parts[1])
    except:
        bot.reply_to(message, "❌ ID цели должен быть числом.")
        return
    if target not in game.players:
        bot.reply_to(message, "❌ Такого игрока нет.")
        return
    if not game.is_alive(target):
        bot.reply_to(message, "❌ Цель мертва.")
        return
    if game.night_action(uid, target):
        bot.reply_to(message, f"✅ Действие сохранено. Жди рассвета.")
    else:
        bot.reply_to(message, "❌ Нельзя совершить действие (возможно, ты Мирный или уже действовал).")

@bot.message_handler(commands=['vote'])
def vote(message: Message):
    chat_id = message.chat.id
    game = games.get(chat_id)
    if not game or game.phase != "voting":
        bot.reply_to(message, "❌ Сейчас нельзя голосовать.")
        return
    uid = message.from_user.id
    if not game.is_alive(uid):
        bot.reply_to(message, "❌ Мёртвые не голосуют.")
        return
    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "❌ Использование: /vote <id цели>")
        return
    try:
        target = int(parts[1])
    except:
        bot.reply_to(message, "❌ ID цели должен быть числом.")
        return
    if target not in game.players or not game.is_alive(target):
        bot.reply_to(message, "❌ Цель мертва или не существует.")
        return
    if game.vote(uid, target):
        bot.reply_to(message, f"✅ Голос за {game.players[target]} учтён.")
    else:
        bot.reply_to(message, "❌ Ошибка голосования.")

@bot.message_handler(commands=['status'])
def status(message: Message):
    chat_id = message.chat.id
    game = games.get(chat_id)
    if not game:
        bot.reply_to(message, "❌ Нет активной игры.")
        return
    text = f"📊 **Статус игры**\n"
    text += f"Фаза: {game.phase}\n"
    text += f"День: {game.day_num}\n"
    text += f"Живы ({len(game.alive)}): " + ", ".join([game.players[uid] for uid in game.alive]) + "\n"
    if game.phase == "voting":
        vote_summary = ", ".join([f"{game.players[uid]}: {v}" for uid, v in game.votes.items()])
        text += f"Голосов: {vote_summary if vote_summary else 'пока нет'}"
    bot.reply_to(message, text, parse_mode='Markdown')

@bot.message_handler(commands=['nextphase'])
def nextphase(message: Message):
    chat_id = message.chat.id
    game = games.get(chat_id)
    if not game:
        bot.reply_to(message, "❌ Нет игры.")
        return
    if message.from_user.id != game.creator_id:
        bot.reply_to(message, "❌ Только создатель может переключать фазы.")
        return
    new_phase, data = game.next_phase()
    if new_phase == "day":
        results = data
        msg = f"☀️ Наступил день {game.day_num}\n"
        if results:
            msg += "\n".join(results)
        else:
            msg += "Ночь прошла спокойно."
        winner = game.check_win()
        if winner:
            msg += f"\n\n🏆 **{winner} победили!** Игра окончена."
            del games[chat_id]
        bot.send_message(chat_id, msg, parse_mode='Markdown')
    elif new_phase == "voting":
        bot.send_message(chat_id, f"🗳️ Началось голосование. Пишите /vote <id цели>")
    elif new_phase == "exiled":
        exiled = data
        msg = f"⚖️ По результатам голосования изгнан {game.players[exiled]}. Это был(а) {game.roles[exiled]}.\n"
        winner = game.check_win()
        if winner:
            msg += f"\n🏆 **{winner} победили!** Игра окончена."
            del games[chat_id]
        else:
            msg += f"🌙 Наступает ночь {game.day_num}."
        bot.send_message(chat_id, msg, parse_mode='Markdown')
    elif new_phase == "no_exile":
        bot.send_message(chat_id, f"🤝 Никто не изгнан. Наступает ночь {game.day_num}.")
    else:
        bot.reply_to(message, "⚠️ Неизвестная фаза.")

# ========== ЗАПУСК ==========
if __name__ == '__main__':
    print("🤖 Mafia Hack Bot запущен")
    print(f"🔑 Админы: {ADMIN_IDS}")
    try:
        bot.infinity_polling()
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен.")
