import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
from datetime import datetime
import pytz
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(".env")

# Get the bot token from the environment variable
TOKEN = os.getenv("DISCORD_TOKEN")
# Bot setup
bot = commands.Bot(command_prefix=None, intents=discord.Intents.default())

LOG_CHANNEL_ID = 1321354926567456810  # Replace with your logging channel ID
TARGET_GUILD_ID = 1180200730854953131  # Replace with your server's guild ID (DEDZ, for example)

# Define the IST timezone
IST = pytz.timezone('Asia/Kolkata')

# Function to log actions to a specific server and channel
async def log_action(message: str, guild, channel):
    # Get the target guild where logs will be sent
    target_guild = bot.get_guild(TARGET_GUILD_ID)
    
    if target_guild:
        # Get the log channel in the target guild
        log_channel = target_guild.get_channel(LOG_CHANNEL_ID)
        
        if log_channel:
            # Get the current time in IST
            ist_time = datetime.now(IST)
            timestamp = ist_time.strftime('%Y-%m-%d %H:%M:%S')

            log_message = (
                f"**[{timestamp}]**\n"
                f"**Server**: {guild.name}\n"
                f"**Channel**: #{channel.name}\n"
                f"**Action**: {message}\n"
            )
            try:
                # Send the log message to the log channel in the target guild
                await log_channel.send(log_message)
            except discord.Forbidden:
                print(f"Bot doesn't have permission to send messages in the log channel of {target_guild.name}.")
        else:
            print(f"Log channel not found in the target guild: {target_guild.name}")
    else:
        print("Target guild not found.")

# Example of a command that triggers logging
@bot.event
async def on_ready():
    print(f"Bot is online as {bot.user}")
    # Log the bot's startup action to the log channel of the target guild
    # Set bot's initial status
    await bot.change_presence(
        activity=discord.Game(name="Music🎧"),
        status=discord.Status.dnd,
    )
    target_guild = bot.get_guild(TARGET_GUILD_ID)
    if target_guild:
        log_channel = target_guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            timestamp = datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')
            log_message = f"[{timestamp}] Bot started and is online."
            await log_channel.send(log_message)

# Your other bot commands (like play, join, etc.) would call log_action as needed.

# Example of a command where logs are generated for a command used in any guild
@bot.command()
async def test(ctx):
    # Example action: log when a test command is used
    await log_action(f"Test command executed by {ctx.author}.", ctx.guild, ctx.channel)
    await ctx.send("Test command executed!")


# YTDLSource class to handle YouTube audio extraction
class YTDLSource(discord.PCMVolumeTransformer):
    YDL_OPTIONS = {
        'format': 'bestaudio',
        'noplaylist': True,
        'source_address': '0.0.0.0',
        'quiet': True,
        'no_warnings': True,
        'skip_download': True  # Skip download to stream directly
    }

    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(cls.YDL_OPTIONS) as ydl:
            try:
                data = await loop.run_in_executor(None, ydl.extract_info, url)
                if 'entries' in data:
                    data = data['entries'][0]  # Use the first entry if it's a playlist

                # Use the streamable URL directly
                return cls(
                    discord.FFmpegPCMAudio(
                        data['url'],
                        before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
                    ),
                    data=data
                )
            except Exception as e:
                print(f"Error in YTDLSource.from_url: {e}")
                raise

queue = []

# Commands
@bot.tree.command(name="join", description="Bot joins the voice channel.")
async def join(interaction: discord.Interaction):
    if interaction.user.voice:
        channel = interaction.user.voice.channel
        if interaction.guild.voice_client is None:
            await channel.connect()
            await interaction.response.send_message("Joined the voice channel!")
            await log_action(f"Joined voice channel: {channel.name} by {interaction.user}.", interaction.guild, channel)
        else:
            await interaction.response.send_message("I'm already in a voice channel.", ephemeral=True)
    else:
        await interaction.response.send_message("You need to be in a voice channel to use this command.", ephemeral=True)

@bot.tree.command(name="play", description="Play a song from a URL")
async def play(interaction: discord.Interaction, url: str):
    await interaction.response.defer(thinking=True)
    if interaction.guild.voice_client is None:
        if interaction.user.voice:
            await interaction.user.voice.channel.connect()
        else:
            await interaction.followup.send("You need to be in a voice channel to use this command.", ephemeral=True)
            return

    queue.append(url)
    if interaction.guild.voice_client.is_playing():
        await interaction.followup.send(f'Added to queue: {url}')
        await log_action(f"Added to queue: {url} by {interaction.user}.", interaction.guild, interaction.channel)
    else:
        await play_next(interaction)

async def play_next(interaction: discord.Interaction):
    if queue:
        url = queue.pop(0)
        try:
            player = await YTDLSource.from_url(url, loop=bot.loop)
            interaction.guild.voice_client.play(
                player,
                after=lambda e: asyncio.run_coroutine_threadsafe(after_play(interaction), bot.loop) if e is None else print(f"Playback error: {e}")
            )
            await interaction.followup.send(f'Now playing: {player.title}')
            await log_action(f"Now playing: {player.title} by {interaction.user}.", interaction.guild, interaction.channel)
        except Exception as e:
            await log_action(f"Error during play_next: {e}", interaction.guild, interaction.channel)
            await interaction.followup.send(f'Error occurred: {str(e)}')
            await play_next(interaction)  # Continue with the next song if error occurs
    else:
        await log_action("Queue is empty.", interaction.guild, interaction.channel)
        await interaction.followup.send("Queue is empty.")

async def after_play(interaction: discord.Interaction):
    await asyncio.sleep(1)
    await play_next(interaction)

@bot.tree.command(name="skip", description="Skip the current song.")
async def skip(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.stop()  # This will trigger the after callback to play the next song
        await interaction.response.send_message("Skipped the current song.")
        await log_action(f"{interaction.user} skipped the current song.", interaction.guild, interaction.channel)
    else:
        await interaction.response.send_message("No music is playing to skip.", ephemeral=True)

@bot.tree.command(name="leave", description="Disconnect from the voice channel.")
async def leave(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client:
        await voice_client.disconnect()
        await interaction.response.send_message("Disconnected from the voice channel.")
        await log_action(f"Bot disconnected from the voice channel by {interaction.user}.", interaction.guild, interaction.channel)
    else:
        await interaction.response.send_message("I'm not in a voice channel.", ephemeral=True)

@bot.tree.command(name="help", description="Show available commands.")
async def help_command(interaction: discord.Interaction):
    await interaction.response.send_message("Available commands: /play, /skip, /activity, /join, /leave, /stop, etc.")
    await log_action(f"{interaction.user} accessed the help menu.", interaction.guild, interaction.channel)

@bot.tree.command(name="activity", description="Change the bot's activity")
@app_commands.describe(
    activity_type="The type of activity (playing, listening, watching, streaming)", 
    activity_name="The name of the activity",
    stream_url="The URL for streaming (required for 'streaming' activity)"
)
async def set_activity(interaction: discord.Interaction, activity_type: str, activity_name: str, stream_url: str = None):
    activity = None

    # Match the activity types
    if activity_type.lower() == "playing":
        activity = discord.Game(name=activity_name)
    elif activity_type.lower() == "listening":
        activity = discord.Activity(type=discord.ActivityType.listening, name=activity_name)
    elif activity_type.lower() == "watching":
        activity = discord.Activity(type=discord.ActivityType.watching, name=activity_name)
    elif activity_type.lower() == "streaming":
        if not stream_url:
            await interaction.response.send_message(
                "You must provide a streaming URL for the 'streaming' activity type.", ephemeral=True
            )
            return
        activity = discord.Streaming(name=activity_name, url=stream_url)
    else:
        await interaction.response.send_message(
            "Invalid activity type! Use 'playing', 'listening', 'watching', or 'streaming'.", 
            ephemeral=True
        )
        return

    # Update the bot's presence
    try:
        await bot.change_presence(activity=activity)
        await interaction.response.send_message(
            f"Bot activity changed to {activity_type} {activity_name}!", ephemeral=True
        )

        # Log the activity change
        await log_action(f"{interaction.user} changed the bot's activity to {activity_type} {activity_name}.", interaction.guild, interaction.channel)

    except Exception as e:
        await interaction.response.send_message(f"An error occurred: {e}", ephemeral=True)

# Running the bot
bot.run(TOKEN)


