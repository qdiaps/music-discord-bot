import discord
from discord.ext import commands, tasks
import os
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('music_bot')

TOKEN = os.getenv('DISCORD_TOKEN')
DOWNLOAD_CHANNEL_ID = os.getenv('DOWNLOAD_CHANNEL_ID')
DOWNLOAD_CHANNEL_ID = int(DOWNLOAD_CHANNEL_ID) if DOWNLOAD_CHANNEL_ID else None

MUSIC_DIR = './music'
SUPPORTED_FORMATS = ('.mp3', '.wav', '.flac', '.ogg', '.m4a')

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
        self.download_channel_id = DOWNLOAD_CHANNEL_ID

state = MusicState()

if not os.path.exists(MUSIC_DIR):
    os.makedirs(MUSIC_DIR)

def update_playlist():
    state.playlist = sorted([
        f for f in os.listdir(MUSIC_DIR) 
        if f.lower().endswith(SUPPORTED_FORMATS)
    ])

def get_current_song_name():
    if not state.playlist:
        return "Плейлист пуст"
    return state.playlist[state.current_index - 1 if state.current_index > 0 else -1]

def get_next_song_name():
    if not state.playlist:
        return "Плейлист пуст"
    return state.playlist[state.current_index]

@bot.event
async def on_ready():
    update_playlist()
    logger.info(f"Бот авторизован как {bot.user}")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    logger.error(f"Command error: {error}")

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
                    update_playlist()
                    logger.info(f"Файл сохранен: {attachment.filename}")
                    await message.add_reaction('✅')
    
    await bot.process_commands(message)

@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="Информация о боте и команды",
        description="Бот для круглосуточного воспроизведения локальных аудиофайлов.",
        color=discord.Color.blue()
    )
    embed.add_field(name="!start", value="Запустить воспроизведение", inline=False)
    embed.add_field(name="!stop", value="Остановить воспроизведение и выйти", inline=False)
    embed.add_field(name="!pause", value="Поставить музыку на паузу", inline=False)
    embed.add_field(name="!resume", value="Снять с паузы", inline=False)
    embed.add_field(name="!next", value="Включить следующий трек", inline=False)
    embed.add_field(name="!back", value="Включить предыдущий трек", inline=False)
    embed.add_field(name="!vol [0-100]", value="Изменить громкость", inline=False)
    embed.add_field(name="!list [страница]", value="Показать список всех треков", inline=False)
    embed.add_field(name="!set_channel [ID]", value="Установить канал для загрузки музыки", inline=False)
    
    status_text = f"Треков в базе: {len(state.playlist)}\nКанал загрузки: {state.download_channel_id or 'Не установлен'}"
    embed.set_footer(text=status_text)
    
    await ctx.send(embed=embed)

@bot.command()
async def set_channel(ctx, channel_id: int):
    state.download_channel_id = channel_id
    logger.info(f"Канал загрузки изменен на {channel_id}")
    await ctx.send(f"Канал для загрузки музыки установлен: {channel_id}")

@bot.command()
async def start(ctx):
    if not ctx.author.voice:
        return await ctx.send("Ошибка: пользователь не в голосовом канале.")
    
    vc = ctx.voice_client or await ctx.author.voice.channel.connect()
    
    if not radio_loop.is_running():
        update_playlist()
        radio_loop.start(vc)
        song = get_next_song_name()
        await ctx.send(f"Воспроизведение запущено. Сейчас играет: {song}")

@bot.command()
async def stop(ctx):
    vc = ctx.voice_client
    if vc:
        radio_loop.cancel()
        await vc.disconnect()
        state.is_paused = False
        await ctx.send("Воспроизведение остановлено.")

@bot.command()
async def pause(ctx):
    vc = ctx.voice_client
    if vc and vc.is_playing():
        vc.pause()
        state.is_paused = True
        song = get_current_song_name()
        await ctx.send(f"Пауза. Текущий трек: {song}")

@bot.command()
async def resume(ctx):
    vc = ctx.voice_client
    if vc and vc.is_paused():
        vc.resume()
        state.is_paused = False
        song = get_current_song_name()
        await ctx.send(f"Воспроизведение возобновлено. Играет: {song}")

@bot.command()
async def next(ctx):
    vc = ctx.voice_client
    if vc:
        vc.stop()
        song = get_next_song_name()
        await ctx.send(f"Пропуск. Следующий трек: {song}")

@bot.command()
async def back(ctx):
    vc = ctx.voice_client
    if vc:
        if len(state.playlist) > 0:
            state.current_index = (state.current_index - 2) % len(state.playlist)
            song = get_next_song_name()
            vc.stop()
            await ctx.send(f"Возврат. Включаю: {song}")

@bot.command()
async def vol(ctx, volume: int):
    if 0 <= volume <= 100:
        state.volume = volume / 100
        vc = ctx.voice_client
        if vc and vc.source:
            vc.source.volume = state.volume
        await ctx.send(f"Громкость: {volume}%")

@bot.command()
async def list(ctx, page: int = 1):
    update_playlist()
    if not state.playlist:
        return await ctx.send("Список треков пуст.")
    
    items_per_page = 40
    pages = (len(state.playlist) - 1) // items_per_page + 1
    
    if page < 1 or page > pages:
        return await ctx.send(f"Ошибка: укажите страницу от 1 до {pages}.")
    
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    current_page_list = state.playlist[start_idx:end_idx]
    
    response = f"Список треков (Страница {page}/{pages}):\n```\n"
    for i, name in enumerate(current_page_list, start=start_idx + 1):
        response += f"{i}. {name}\n"
    response += "```"
    
    await ctx.send(response)

@tasks.loop(seconds=2)
async def radio_loop(vc):
    if not vc.is_playing() and not state.is_paused:
        if not state.playlist:
            return

        if state.current_index >= len(state.playlist):
            state.current_index = 0
        
        song_name = state.playlist[state.current_index]
        path = os.path.join(MUSIC_DIR, song_name)
        
        try:
            source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(path), 
                volume=state.volume
            )
            vc.play(source)
            await bot.change_presence(activity=discord.Game(name=song_name))
            state.current_index = (state.current_index + 1) % len(state.playlist)
        except Exception as e:
            logger.error(f"Play error: {e}")
            state.current_index = (state.current_index + 1) % len(state.playlist)

bot.run(TOKEN)