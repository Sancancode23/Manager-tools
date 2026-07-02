import os
import re
import asyncio
import datetime
from collections import defaultdict, deque
from typing import Optional

import discord
from discord.ext import commands
from dotenv import load_dotenv


# =========================
# CONFIG - EDIT THESE
# =========================

PREFIX = "!"

WELCOME_CHANNEL_ID = 1522304961516404829   # replace with your welcome channel ID
GOODBYE_CHANNEL_ID = 1522303325217755286   # replace with your goodbye channel ID
MOD_LOG_CHANNEL_ID = 1522312326370562089   # replace with your mod-log channel ID

WELCOME_GIF_PATH = "assets/welcome.gif"   # you can replace this gif
GOODBYE_GIF_PATH = "assets/goodbye.gif"   # you can replace this gif

ANTI_INVITE_LINKS = True
ANTI_MASS_MENTION = True
ANTI_SPAM = True

SPAM_LIMIT = 5          # messages
SPAM_SECONDS = 7        # within seconds
SPAM_TIMEOUT_MINUTES = 10

MAX_MENTIONS_ALLOWED = 6


# =========================
# BOT SETUP
# =========================

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True
intents.messages = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None
)

user_message_times = defaultdict(lambda: deque(maxlen=SPAM_LIMIT))


# =========================
# HELPER FUNCTIONS
# =========================

def parse_duration(duration: str) -> datetime.timedelta:
    """
    Examples:
    10s = 10 seconds
    5m = 5 minutes
    2h = 2 hours
    7d = 7 days
    """
    match = re.fullmatch(r"(\d+)(s|m|h|d)", duration.lower().strip())

    if not match:
        raise ValueError("Invalid duration format.")

    amount = int(match.group(1))
    unit = match.group(2)

    if unit == "s":
        return datetime.timedelta(seconds=amount)
    if unit == "m":
        return datetime.timedelta(minutes=amount)
    if unit == "h":
        return datetime.timedelta(hours=amount)
    if unit == "d":
        return datetime.timedelta(days=amount)

    raise ValueError("Invalid duration unit.")


def is_mod_safe(ctx: commands.Context, member: discord.Member) -> bool:
    """
    Prevents mods from targeting owners, admins above them, or the bot itself.
    """
    if member == ctx.guild.owner:
        return False

    if member == ctx.author:
        return False

    if member == ctx.guild.me:
        return False

    if ctx.author != ctx.guild.owner and member.top_role >= ctx.author.top_role:
        return False

    if member.top_role >= ctx.guild.me.top_role:
        return False

    return True


async def send_mod_log(guild: discord.Guild, title: str, description: str):
    channel = guild.get_channel(MOD_LOG_CHANNEL_ID)

    if not channel:
        return

    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.blurple(),
        timestamp=discord.utils.utcnow()
    )

    await channel.send(embed=embed)


async def send_embed_with_optional_gif(
    channel: discord.TextChannel,
    embed: discord.Embed,
    gif_path: str,
    content: Optional[str] = None
):
    if gif_path and os.path.exists(gif_path):
        filename = os.path.basename(gif_path)
        file = discord.File(gif_path, filename=filename)
        embed.set_image(url=f"attachment://{filename}")
        await channel.send(content=content, embed=embed, file=file)
    else:
        await channel.send(content=content, embed=embed)


async def try_delete_message(message: discord.Message):
    try:
        await message.delete()
    except discord.Forbidden:
        pass
    except discord.NotFound:
        pass


# =========================
# EVENTS
# =========================

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    print(f"Prefix: {PREFIX}")
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{PREFIX}help"
        )
    )


@bot.event
async def on_member_join(member: discord.Member):
    channel = member.guild.get_channel(WELCOME_CHANNEL_ID)

    if channel:
        embed = discord.Embed(
            title="Welcome!",
            description=f"{member.mention} joined **{member.guild.name}**.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Member Count", value=str(member.guild.member_count), inline=True)

        await send_embed_with_optional_gif(
            channel=channel,
            embed=embed,
            gif_path=WELCOME_GIF_PATH,
            content=f"Welcome {member.mention}!"
        )

    account_age = discord.utils.utcnow() - member.created_at

    if account_age < datetime.timedelta(days=2):
        await send_mod_log(
            member.guild,
            "Security Alert: New Account Joined",
            f"{member.mention} joined with an account less than 2 days old."
        )


@bot.event
async def on_member_remove(member: discord.Member):
    channel = member.guild.get_channel(GOODBYE_CHANNEL_ID)

    if channel:
        embed = discord.Embed(
            title="Goodbye!",
            description=f"**{member}** left the server.",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Member Count", value=str(member.guild.member_count), inline=True)

        await send_embed_with_optional_gif(
            channel=channel,
            embed=embed,
            gif_path=GOODBYE_GIF_PATH
        )


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    if isinstance(message.author, discord.Member):
        if message.author.guild_permissions.manage_messages:
            await bot.process_commands(message)
            return

    content = message.content.lower()

    # Anti invite links
    if ANTI_INVITE_LINKS:
        invite_patterns = [
            "discord.gg/",
            "discord.com/invite/",
            "discordapp.com/invite/"
        ]

        if any(pattern in content for pattern in invite_patterns):
            await try_delete_message(message)

            try:
                await message.channel.send(
                    f"{message.author.mention}, invite links are not allowed here.",
                    delete_after=5
                )
            except discord.Forbidden:
                pass

            await send_mod_log(
                message.guild,
                "Invite Link Blocked",
                f"User: {message.author.mention}\nChannel: {message.channel.mention}"
            )
            return

    # Anti mass mention
    if ANTI_MASS_MENTION:
        mention_count = len(message.mentions) + len(message.role_mentions)

        if mention_count >= MAX_MENTIONS_ALLOWED:
            await try_delete_message(message)

            try:
                await message.author.timeout(
                    datetime.timedelta(minutes=SPAM_TIMEOUT_MINUTES),
                    reason="Mass mention protection"
                )
            except discord.Forbidden:
                pass

            await send_mod_log(
                message.guild,
                "Mass Mention Blocked",
                f"User: {message.author.mention}\nMentions: {mention_count}"
            )
            return

    # Anti spam
    if ANTI_SPAM:
        now = datetime.datetime.now().timestamp()
        times = user_message_times[message.author.id]
        times.append(now)

        if len(times) == SPAM_LIMIT and now - times[0] <= SPAM_SECONDS:
            await try_delete_message(message)

            try:
                await message.author.timeout(
                    datetime.timedelta(minutes=SPAM_TIMEOUT_MINUTES),
                    reason="Spam protection"
                )
                await message.channel.send(
                    f"{message.author.mention} has been timed out for spam.",
                    delete_after=6
                )
            except discord.Forbidden:
                pass

            await send_mod_log(
                message.guild,
                "Spam Protection Triggered",
                f"User: {message.author.mention}\nAction: Timeout for {SPAM_TIMEOUT_MINUTES} minutes"
            )
            return

    await bot.process_commands(message)


# =========================
# MODERATION COMMANDS
# =========================

@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
@commands.bot_has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    if not is_mod_safe(ctx, member):
        return await ctx.reply("I can’t kick this user because of role hierarchy or safety rules.")

    await member.kick(reason=f"{reason} | By {ctx.author}")
    await ctx.reply(f"✅ Kicked **{member}**. Reason: {reason}")

    await send_mod_log(
        ctx.guild,
        "User Kicked",
        f"User: {member}\nModerator: {ctx.author.mention}\nReason: {reason}"
    )


@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
@commands.bot_has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    if not is_mod_safe(ctx, member):
        return await ctx.reply("I can’t ban this user because of role hierarchy or safety rules.")

    await member.ban(reason=f"{reason} | By {ctx.author}")
    await ctx.reply(f"✅ Banned **{member}**. Reason: {reason}")

    await send_mod_log(
        ctx.guild,
        "User Banned",
        f"User: {member}\nModerator: {ctx.author.mention}\nReason: {reason}"
    )


@bot.command(name="unban")
@commands.has_permissions(ban_members=True)
@commands.bot_has_permissions(ban_members=True)
async def unban(ctx, user_id: int, *, reason: str = "No reason provided"):
    user = await bot.fetch_user(user_id)
    await ctx.guild.unban(user, reason=f"{reason} | By {ctx.author}")

    await ctx.reply(f"✅ Unbanned **{user}**.")

    await send_mod_log(
        ctx.guild,
        "User Unbanned",
        f"User: {user}\nModerator: {ctx.author.mention}\nReason: {reason}"
    )


@bot.command(name="timeout", aliases=["mute"])
@commands.has_permissions(moderate_members=True)
@commands.bot_has_permissions(moderate_members=True)
async def timeout(ctx, member: discord.Member, duration: str, *, reason: str = "No reason provided"):
    if not is_mod_safe(ctx, member):
        return await ctx.reply("I can’t timeout this user because of role hierarchy or safety rules.")

    try:
        delta = parse_duration(duration)
    except ValueError:
        return await ctx.reply("Use duration like `10s`, `5m`, `2h`, or `7d`.")

    if delta > datetime.timedelta(days=28):
        return await ctx.reply("Maximum timeout is 28 days.")

    await member.timeout(delta, reason=f"{reason} | By {ctx.author}")
    await ctx.reply(f"✅ Timed out **{member}** for `{duration}`. Reason: {reason}")

    await send_mod_log(
        ctx.guild,
        "User Timed Out",
        f"User: {member.mention}\nModerator: {ctx.author.mention}\nDuration: {duration}\nReason: {reason}"
    )


@bot.command(name="unmute", aliases=["untimeout"])
@commands.has_permissions(moderate_members=True)
@commands.bot_has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    if not is_mod_safe(ctx, member):
        return await ctx.reply("I can’t unmute this user because of role hierarchy or safety rules.")

    await member.timeout(None, reason=f"{reason} | By {ctx.author}")
    await ctx.reply(f"✅ Removed timeout from **{member}**.")

    await send_mod_log(
        ctx.guild,
        "Timeout Removed",
        f"User: {member.mention}\nModerator: {ctx.author.mention}\nReason: {reason}"
    )


@bot.command(name="purge", aliases=["clear"])
@commands.has_permissions(manage_messages=True)
@commands.bot_has_permissions(manage_messages=True)
async def purge(ctx, amount: int):
    if amount < 1 or amount > 100:
        return await ctx.reply("Use a number between `1` and `100`.")

    deleted = await ctx.channel.purge(limit=amount + 1)

    msg = await ctx.send(f"✅ Deleted `{len(deleted) - 1}` messages.")
    await asyncio.sleep(4)
    await msg.delete()

    await send_mod_log(
        ctx.guild,
        "Messages Purged",
        f"Moderator: {ctx.author.mention}\nChannel: {ctx.channel.mention}\nAmount: {len(deleted) - 1}"
    )


# =========================
# AVATAR / BANNER COMMANDS
# =========================

@bot.command(name="avatar", aliases=["av", "pfp"])
async def avatar(ctx, member: Optional[discord.Member] = None):
    member = member or ctx.author

    embed = discord.Embed(
        title=f"{member}'s Avatar",
        color=discord.Color.blurple()
    )
    embed.set_image(url=member.display_avatar.replace(size=1024).url)

    await ctx.reply(embed=embed)


@bot.command(name="banner")
async def banner(ctx, member: Optional[discord.Member] = None):
    member = member or ctx.author
    user = await bot.fetch_user(member.id)

    embed = discord.Embed(
        title=f"{member}'s Banner",
        color=discord.Color.blurple()
    )

    if user.banner:
        embed.set_image(url=user.banner.replace(size=1024).url)
        await ctx.reply(embed=embed)
    else:
        await ctx.reply("This user does not have a visible banner.")


@bot.command(name="servericon", aliases=["icon"])
async def server_icon(ctx):
    if not ctx.guild.icon:
        return await ctx.reply("This server has no icon.")

    embed = discord.Embed(
        title=f"{ctx.guild.name}'s Icon",
        color=discord.Color.blurple()
    )
    embed.set_image(url=ctx.guild.icon.replace(size=1024).url)

    await ctx.reply(embed=embed)


# =========================
# SECURITY COMMAND
# =========================

@bot.command(name="security")
@commands.has_permissions(manage_guild=True)
async def security(ctx):
    embed = discord.Embed(
        title="Security Settings",
        color=discord.Color.blurple()
    )

    embed.add_field(name="Anti Invite Links", value=str(ANTI_INVITE_LINKS), inline=False)
    embed.add_field(name="Anti Mass Mention", value=str(ANTI_MASS_MENTION), inline=False)
    embed.add_field(name="Anti Spam", value=str(ANTI_SPAM), inline=False)
    embed.add_field(
        name="Spam Rule",
        value=f"{SPAM_LIMIT} messages in {SPAM_SECONDS} seconds = {SPAM_TIMEOUT_MINUTES} min timeout",
        inline=False
    )

    await ctx.reply(embed=embed)


@bot.command(name="ping")
async def ping(ctx):
    latency = round(bot.latency * 1000)

    embed = discord.Embed(
        title="Pong!",
        description=f"Bot latency: `{latency}ms`",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )

    await ctx.reply(embed=embed)


@bot.command(name="renamechannel", aliases=["channelname", "setchannelname"])
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_channels=True)
async def rename_channel(ctx, *, new_name: str):
    """
    Renames the channel where this command is used.
    Example:
    !renamechannel general-chat
    """
    old_name = ctx.channel.name
    clean_name = new_name.lower().replace(" ", "-")

    await ctx.channel.edit(
        name=clean_name,
        reason=f"Channel renamed by {ctx.author}"
    )

    await ctx.reply(f"✅ Channel renamed from `#{old_name}` to `#{clean_name}`.")

    await send_mod_log(
        ctx.guild,
        "Channel Renamed",
        f"Moderator: {ctx.author.mention}\nOld Name: #{old_name}\nNew Name: #{clean_name}"
    )


@bot.command(name="renamechannelof", aliases=["renamech"])
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_channels=True)
async def rename_channel_of(ctx, channel: discord.TextChannel, *, new_name: str):
    """
    Renames a mentioned channel.
    Example:
    !renamechannelof #general general-chat
    """
    old_name = channel.name
    clean_name = new_name.lower().replace(" ", "-")

    await channel.edit(
        name=clean_name,
        reason=f"Channel renamed by {ctx.author}"
    )

    await ctx.reply(f"✅ Channel renamed from `#{old_name}` to `#{clean_name}`.")

    await send_mod_log(
        ctx.guild,
        "Channel Renamed",
        f"Moderator: {ctx.author.mention}\nOld Name: #{old_name}\nNew Name: #{clean_name}"
    )




# =========================
# HELP COMMAND
# =========================

@bot.command(name="help")
async def help_command(ctx):
    embed = discord.Embed(
        title="Bot Commands",
        description=f"Prefix: `{PREFIX}`",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="Welcome / Goodbye",
        value="Auto welcome and goodbye messages with replaceable GIFs.",
        inline=False
    )

    embed.add_field(
        name="Moderation",
        value=(
            "`!kick @user reason`\n"
            "`!ban @user reason`\n"
            "`!unban user_id reason`\n"
            "`!mute @user 10m reason`\n"
            "`!timeout @user 2h reason`\n"
            "`!unmute @user reason`\n"
            "`!purge 20`"
        ),
        inline=False
    )

    embed.add_field(
        name="Profile",
        value=(
            "`!avatar @user`\n"
            "`!banner @user`\n"
            "`!servericon`"
        ),
        inline=False
    )

    embed.add_field(
        name="Utility",
        value="`!ping`",
        inline=False
    )

    embed.add_field(
        name="Server Management",
        value=(
            "`!renamechannel new-channel-name` - renames the current channel\n"
            "`!renamechannelof #channel new-channel-name` - renames a mentioned channel"
        ),
        inline=False
    )

    embed.add_field(
        name="Security",
        value="`!security`",
        inline=False
    )

    await ctx.reply(embed=embed)


# =========================
# ERROR HANDLER
# =========================

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.MissingPermissions):
        return await ctx.reply("You don’t have permission to use this command.")

    if isinstance(error, commands.BotMissingPermissions):
        missing = ", ".join(error.missing_permissions)
        return await ctx.reply(f"I’m missing these permissions: `{missing}`")

    if isinstance(error, commands.MissingRequiredArgument):
        return await ctx.reply(f"Missing argument: `{error.param.name}`. Use `{PREFIX}help`.")

    if isinstance(error, commands.BadArgument):
        return await ctx.reply("Invalid user or argument. Mention the user properly or check the format.")

    print(error)
    await ctx.reply("Something went wrong. Check the console error.")


# =========================
# RUN BOT
# =========================

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing. Add it inside your .env file.")

bot.run(TOKEN)
