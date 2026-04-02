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
        self.last_song_name = None
        self.skip_triggered = False
        self.load_config()

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.volume = data.get('volume', 0.5)
                    self.download_channel_id = data.get('download_channel_id')
                    self.last_song_name = data.get('last_song_name')
                    self.repeat_mode = data.get('repeat_mode', False)
                logger.info("Конфигурация загружена")
            except Exception as e:
                logger.error(f"Ошибка загрузки конфига: {e}")

    def save_config(self):
        try:
            data = {
                'volume': self.volume,
                'download_channel_id': self.download_channel_id,
                'last_song_name': self.get_current_song_name() if self.playlist else self.last_song_name,
                'repeat_mode': self.repeat_mode
            }
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"Ошибка сохранения конфига: {e}")

    def update_playlist(self):
        old_song = self.get_current_song_name()
        self.playlist = sorted([
            f for f in os.listdir(MUSIC_DIR) 
            if f.lower().endswith(SUPPORTED_FORMATS)
        ])
        if old_song in self.playlist:
            self.current_index = self.playlist.index(old_song)
        elif self.playlist:
            self.current_index = self.current_index % len(self.playlist)

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
    embed = discord.Embed(title="Команды бота", color=discord.Color.blue())
    commands_list = [
        ("!start", "Запустить плеер"),
        ("!stop", "Остановить и выйти"),
        ("!pause", "Пауза"),
        ("!resume", "Продолжить"),
        ("!next", "Следующий трек"),
        ("!back", "Предыдущий трек"),
        ("!repeat", "Вкл/Выкл повтор текущего трека"),
        ("!play [название]", "Включить конкретный файл"),
        ("!rm [название]", "Удалить файл"),
        ("!vol [0-100]", "Громкость"),
        ("!list [стр]", "Список треков"),
        ("!set_channel [ID]", "Канал для загрузки")
    ]
    for cmd, desc in commands_list:
        embed.add_field(name=cmd, value=desc, inline=False)
    
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
        return await ctx.send("Ошибка: вы не в голосовом канале.")
    
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
async def play(ctx, *, name: str):
    state.update_playlist()
    if name in state.playlist:
        state.current_index = state.playlist.index(name)
        vc = ctx.voice_client
        if vc:
            vc.stop()
        else:
            await start(ctx)
        await ctx.send(f"Включаю выбранный трек:\n{format_song_name(name)}")
    else:
        await ctx.send("Файл не найден. Укажите точное имя с расширением из !list.")

@bot.command()
async def rm(ctx, *, name: str):
    if name in state.playlist:
        path = os.path.join(MUSIC_DIR, name)
        current_playing = state.get_current_song_name()
        
        try:
            os.remove(path)
            logger.info(f"Файл удален: {name}")
            
            if name == current_playing:
                vc = ctx.voice_client
                if vc:
                    vc.stop()
            
            state.update_playlist()
            await ctx.send(f"Удалено успешно: {name}")
        except Exception as e:
            logger.error(f"Ошибка при удалении: {e}")
            await ctx.send("Не удалось удалить файл.")
    else:
        await ctx.send("Файл не найден в плейлисте.")

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
        return await ctx.send("Плейлист пуст.")
    
    items_per_page = 50
    pages = (len(state.playlist) - 1) // items_per_page + 1
    if page < 1 or page > pages:
        return await ctx.send(f"Страница должна быть от 1 до {pages}.")
    
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    current_page = state.playlist[start_idx:end_idx]
    
    res = f"Треки (стр {page}/{pages}):\n```\n"
    for i, name in enumerate(current_page, start=start_idx + 1):
        prefix = "▶ " if (i-1) == state.current_index else "  "
        res += f"{prefix}{i}. {name}\n"
    res += "```"
    await ctx.send(res)

@tasks.loop(seconds=1)
async def radio_loop(vc):
    if not vc.is_playing() and not state.is_paused:
        state.update_playlist()
        if not state.playlist:
            return

        if not state.skip_triggered and not state.repeat_mode:
            pass 
        
        state.skip_triggered = False

        song_name = state.get_current_song_name()
        path = os.path.join(MUSIC_DIR, song_name)
        
        try:
            source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(path), 
                volume=state.volume
            )
            def after_playing(error):
                if not state.repeat_mode and not state.skip_triggered:
                    state.current_index = (state.current_index + 1) % len(state.playlist)
                state.skip_triggered = False

            vc.play(source, after=after_playing)
            await bot.change_presence(activity=discord.Game(name=song_name))
        except Exception as e:
            logger.error(f"Ошибка воспроизведения: {e}")
            state.current_index = (state.current_index + 1) % len(state.playlist)

bot.run(TOKEN)