import discord
from discord.ext import commands, tasks
import os
import json
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('music_bot')

TOKEN = os.getenv('DISCORD_TOKEN')
CONFIG_FILE = 'config.json'
DOWNLOAD_CHANNEL_ID = os.getenv('DOWNLOAD_CHANNEL_ID')
DOWNLOAD_CHANNEL_ID = int(DOWNLOAD_CHANNEL_ID) if DOWNLOAD_CHANNEL_ID else None

MUSIC_DIR = './music'
SUPPORTED_FORMATS = ('.mp3', '.wav', '.flac', '.ogg', '.m4a', '.opus')

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix='!', intents=intents)
bot.remove_command('help')

class MusicState:
    def __init__(self):
        self.playlist = []
        self.current_index = 0
        self.volume = 0.5
        self.is_paused = False
        self.repeat_mode = False
        self.download_channel_id = None
        self.skip_triggered = False
        self.load_config()

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.volume = data.get('volume', 0.5)
                    self.download_channel_id = data.get('download_channel_id')
                    self.repeat_mode = data.get('repeat_mode', False)
                logger.info("Конфигурация загружена")
            except Exception as e:
                logger.error(f"Ошибка загрузки конфигурации: {e}")

    def save_config(self):
        try:
            data = {
                'volume': self.volume,
                'download_channel_id': self.download_channel_id,
                'repeat_mode': self.repeat_mode
            }
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"Ошибка сохранения конфигурации: {e}")

    def update_playlist(self):
        self.playlist = sorted([
            f for f in os.listdir(MUSIC_DIR) 
            if f.lower().endswith(SUPPORTED_FORMATS)
        ])

    def get_current_song_name(self):
        if not self.playlist or self.current_index >= len(self.playlist):
            return None
        return self.playlist[self.current_index]

state = MusicState()

if not os.path.exists(MUSIC_DIR):
    os.makedirs(MUSIC_DIR)

def format_song_name(name):
    return f"```\n{name}\n```"

@bot.event
async def on_ready():
    state.update_playlist()
    if state.last_song_name in state.playlist:
        state.current_index = state.playlist.index(state.last_song_name)
    logger.info(f"Бот авторизован как {bot.user}")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Ошибка: пропущен обязательный аргумент.")
        return
        
    logger.error(f"Ошибка выполнения команды: {error}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if state.download_channel_id and message.channel.id == state.download_channel_id:
        if message.attachments:
            for attachment in message.attachments:
                if attachment.filename.lower().endswith(SUPPORTED_FORMATS):
                    file_path = os.path.join(MUSIC_DIR, attachment.filename)
                    await attachment.save(file_path)
                    state.update_playlist()
                    logger.info(f"Файл сохранен: {attachment.filename}")
                    await message.add_reaction('✅')
    await bot.process_commands(message)

@bot.command()
async def help(ctx):
    embed = discord.Embed(title="Команды музыкального бота", color=discord.Color.blue())
    cmds = [
        ("!start", "Запуск плеера."),
        ("!stop", "Остановка и выход"),
        ("!pause / !resume", "Пауза / Продолжить"),
        ("!next / !back", "Переключение треков"),
        ("!repeat", "Вкл/Выкл повтор текущего трека"),
        ("!play [имя или №]", "Включить трек по названию или номеру из списка"),
        ("!rm [имя]", "Удалить файл из библиотеки"),
        ("!vol [0-100]", "Уровень громкости"),
        ("!list [стр]", "Просмотр списка файлов"),
        ("!set_channel [ID]", "Канал для приема файлов")
    ]
    for n, d in cmds:
        embed.add_field(name=n, value=d, inline=False)
    
    status = f"Треков: {len(state.playlist)} | Повтор: {'ВКЛ' if state.repeat_mode else 'ВЫКЛ'}"
    embed.set_footer(text=status)
    await ctx.send(embed=embed)

@bot.command()
async def set_channel(ctx, channel_id: int):
    state.download_channel_id = channel_id
    state.save_config()
    logger.info(f"Канал загрузки: {channel_id}")
    await ctx.send(f"Канал для загрузки установлен: {channel_id}")

@bot.command()
async def start(ctx):
    if not ctx.author.voice:
        return await ctx.send("Ошибка: войдите в голосовой канал.")
    
    vc = ctx.voice_client or await ctx.author.voice.channel.connect()
    
    if radio_loop.is_running():
        if state.is_paused:
            return await resume(ctx)
        return await ctx.send("Плеер уже запущен.")

    state.is_paused = False
    state.update_playlist()
    
    radio_loop.start(vc)
    await ctx.send(f"Воспроизведение запущено.\n{format_song_name(state.get_current_song_name() or 'Плейлист пуст')}")

@bot.command()
async def stop(ctx):
    vc = ctx.voice_client
    if vc:
        radio_loop.cancel()
        await vc.disconnect()
        state.is_paused = False
        state.current_index = 0
        state.save_config()
        await ctx.send("Воспроизведение остановлено.")

@bot.command()
async def pause(ctx):
    vc = ctx.voice_client
    if vc and vc.is_playing():
        vc.pause()
        state.is_paused = True
        await ctx.send(f"Пауза.\n{format_song_name(state.get_current_song_name())}")

@bot.command()
async def resume(ctx):
    vc = ctx.voice_client
    if vc and vc.is_paused():
        vc.resume()
        state.is_paused = False
        await ctx.send(f"Возобновлено.\n{format_song_name(state.get_current_song_name())}")

@bot.command()
async def next(ctx):
    vc = ctx.voice_client
    if vc:
        state.update_playlist()
        if state.playlist:
            state.current_index = (state.current_index + 1) % len(state.playlist)
            state.skip_triggered = True
            vc.stop()
            await ctx.send(f"Пропуск трека. Следующий:\n{format_song_name(state.get_current_song_name())}")

@bot.command()
async def back(ctx):
    vc = ctx.voice_client
    if vc:
        state.update_playlist()
        if state.playlist:
            state.current_index = (state.current_index - 1) % len(state.playlist)
            state.skip_triggered = True
            vc.stop()
            await ctx.send(f"Возврат. Сейчас включу:\n{format_song_name(state.get_current_song_name())}")

@bot.command()
async def repeat(ctx):
    state.repeat_mode = not state.repeat_mode
    state.save_config()
    status = "включен" if state.repeat_mode else "выключен"
    await ctx.send(f"Повтор текущего трека {status}.")

@bot.command()
async def play(ctx, *, target: str):
    state.update_playlist()
    found_idx = -1

    if target.isdigit():
        idx = int(target) - 1
        if 0 <= idx < len(state.playlist):
            found_idx = idx
    else:
        if target in state.playlist:
            found_idx = state.playlist.index(target)

    if found_idx != -1:
        state.current_index = found_idx
        state.skip_triggered = True
        state.save_config()
        
        vc = ctx.voice_client
        if vc:
            vc.stop()
        else:
            await start(ctx)
        await ctx.send(f"Включаю трек №{found_idx + 1}:\n{format_song_name(state.playlist[found_idx])}")
    else:
        await ctx.send("Трек не найден. Укажите точное имя файла или его номер из !list.")

@bot.command()
async def rm(ctx, *, name: str):
    if name in state.playlist:
        path = os.path.join(MUSIC_DIR, name)
        is_current = (name == state.get_current_song_name())
        
        try:
            os.remove(path)
            logger.info(f"Файл удален: {name}")
            
            if is_current:
                vc = ctx.voice_client
                if vc:
                    state.skip_triggered = False
                    vc.stop()
            
            state.update_playlist()
            await ctx.send(f"Файл {name} удален.")
        except Exception as e:
            logger.error(f"Ошибка удаления: {e}")
            await ctx.send("Ошибка при удалении файла.")
    else:
        await ctx.send("Файл не найден.")

@bot.command()
async def vol(ctx, volume: int):
    if 0 <= volume <= 100:
        state.volume = volume / 100
        state.save_config()
        vc = ctx.voice_client
        if vc and vc.source:
            vc.source.volume = state.volume
        await ctx.send(f"Громкость установлена на {volume}%")

@bot.command()
async def list(ctx, page: int = 1):
    state.update_playlist()
    if not state.playlist:
        return await ctx.send("Библиотека пуста.")
    
    ipp = 50
    pages = (len(state.playlist) - 1) // ipp + 1
    if page < 1 or page > pages:
        return await ctx.send(f"Страница {page} не существует. Всего страниц: {pages}")
    
    start_idx = (page - 1) * ipp
    end_idx = start_idx + ipp
    current_page = state.playlist[start_idx:end_idx]
    
    res = f"Список треков (стр {page}/{pages}):\n```\n"
    for i, name in enumerate(current_page, start=start_idx + 1):
        mark = "▶ " if (i-1) == state.current_index else "  "
        res += f"{mark}{i:03d}. {name}\n"
    res += "```"
    await ctx.send(res)

@tasks.loop(seconds=1)
async def radio_loop(vc):
    if not vc.is_playing() and not state.is_paused:
        state.update_playlist()
        if not state.playlist:
            return

        if state.current_index >= len(state.playlist):
            state.current_index = 0
            
        song_name = state.playlist[state.current_index]
        path = os.path.join(MUSIC_DIR, song_name)
        
        if not os.path.exists(path):
            state.update_playlist()
            return

        try:
            source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(path), 
                volume=state.volume
            )
            
            def after_playing(err):
                if err: 
                    logger.error(f"Ошибка после трека: {err}")
                if not state.repeat_mode and not state.skip_triggered:
                    state.current_index = (state.current_index + 1) % len(state.playlist)
                state.skip_triggered = False

            vc.play(source, after=after_playing)
            await bot.change_presence(activity=discord.Game(name=song_name))
            state.save_config()
            
        except Exception as e:
            logger.error(f"Ошибка воспроизведения: {e}")
            state.current_index = (state.current_index + 1) % len(state.playlist)

bot.run(TOKEN)