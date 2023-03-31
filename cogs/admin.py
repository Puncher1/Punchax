from __future__ import annotations

import ast
import json
import textwrap
import traceback
import math
import os
from io import StringIO
from contextlib import redirect_stdout
from typing import TYPE_CHECKING, List, Optional
from enum import Enum

import discord
from discord import ui
from discord.ext import commands
from discord.ext.commands import errors

from .common import Color, Emoji
from .utils.common import str_period_insert
from .utils.dt import Datetime
from .common import GuildID

if TYPE_CHECKING:
    from bot import Punchax
    from .utils.types import Context

DEV_TEST_GUILD_ID = GuildID.dev_test


class _ExtensionState(Enum):
    loaded = 0
    unloaded = 1
    reloaded = 2


class BtnRemoveEmbed(ui.Button):
    async def callback(self, interaction: discord.Interaction):
        await interaction.message.edit(embed=None, content="*Original embed message has been deleted*", view=None)  # type: ignore


class Admin(commands.Cog):
    """Admin-only commands which only can be used by the owner."""

    def __init__(self, bot: Punchax):
        self.bot: Punchax = bot

    async def cog_check(self, ctx: Context) -> bool:
        return await self.bot.is_owner(ctx.author)

    @commands.command()
    async def load(self, ctx: Context, *, extension: str):
        try:
            await self.bot.load_extension(extension)
        except Exception as e:
            content = f"**Failed loading `{extension}`!**\n```{e.__class__.__name__}: {e}```"
        else:
            content = f"**Successfully loaded `{extension}`!**"

        await ctx.reply(content, mention_author=False)

    @commands.command()
    async def unload(self, ctx: Context, *, extension: str):
        try:
            await self.bot.unload_extension(extension)
        except Exception as e:
            content = f"**Failed unloading `{extension}`!**\n```{e.__class__.__name__}: {e}```"
        else:
            content = f"**Successfully unloaded `{extension}`!**"

        await ctx.reply(content, mention_author=False)

    @commands.group(name="reload", aliases=["r"], invoke_without_command=True)
    async def _reload(self, ctx: Context, *, extension: str):
        try:
            await self.bot.reload_extension(extension)
        except Exception as e:
            content = f"**Failed reloading `{extension}`!**\n```{e.__class__.__name__}: {e}```"
        else:
            content = f"**Successfully reloaded `{extension}`!**"

        await ctx.reply(content, mention_author=False)

    async def reload_or_load_extension(self, extension: str) -> _ExtensionState:
        try:
            await self.bot.load_extension(extension)
            ext_state = _ExtensionState.loaded
        except errors.ExtensionAlreadyLoaded:
            await self.bot.reload_extension(extension)
            ext_state = _ExtensionState.reloaded

        return ext_state

    def create_cogs_embed(
        self,
        *,
        loaded: List[str],
        unloaded: List[str],
        reloaded: Optional[List[str]] = None,
        failed: Optional[List[str]] = None,
    ) -> discord.Embed:

        if reloaded is None:
            reloaded = []

        if failed is None:
            failed = []

        loaded_content = "\n".join(loaded)
        unloaded_content = "\n".join(unloaded)
        reloaded_content = "\n".join(reloaded)
        failed_content = "\n".join(failed)

        if len(loaded) > 0:
            loaded_content = f"{Emoji.arrow_up} **Loaded - [{len(loaded)}]**\n{loaded_content}\n\n"

        if len(unloaded) > 0:
            unloaded_content = f"{Emoji.arrow_down} **Unloaded - [{len(unloaded)}]**\n{unloaded_content}\n\n"

        if len(reloaded) > 0:
            reloaded_content = f"{Emoji.arrows_counterclockwise} **Reloaded - [{len(reloaded)}]**\n{reloaded_content}\n\n"

        if len(failed) > 0:
            failed_content = f"{Emoji.x} **Failed - [{len(failed)}]**\n{failed_content}"

        description = f"{loaded_content}{unloaded_content}{reloaded_content}{failed_content}"
        embed = discord.Embed(color=Color.info, description=description)

        return embed

    @_reload.command(name="all")
    async def _reload_all(self, ctx: Context):
        available_extensions = self.bot.get_allowed_extensions()

        loaded = []
        unloaded = []
        reloaded = []
        failed = []

        future_unload = [ext for ext in self.bot.extensions if ext not in available_extensions]
        for extension in future_unload:
            try:
                await self.bot.unload_extension(extension)
                unloaded.append(f"`{extension}`")
            except Exception as e:
                failed.append(f"`{extension}`: `{e.__class__.__name__}`")

        for extension in available_extensions:
            try:
                ext_state = await self.reload_or_load_extension(extension)
            except Exception as e:
                failed.append(f"`{extension}`: `{e.__class__.__name__}`")
            else:
                ext_str = f"`{extension}`"
                if ext_state == _ExtensionState.loaded:
                    loaded.append(ext_str)
                elif ext_state == _ExtensionState.reloaded:
                    reloaded.append(ext_str)

        embed = self.create_cogs_embed(loaded=loaded, unloaded=unloaded, reloaded=reloaded, failed=failed)
        embed.title = "Cogs Update"

        await ctx.reply(embed=embed, mention_author=False)

    @commands.group(name="cogs")
    async def _cogs(self, ctx: Context):
        pass

    @_cogs.command(name="list")
    async def _cogs_list(self, ctx: Context):
        all_extensions = self.bot.get_all_extensions()
        unloaded = [f"`{ext}`" for ext in all_extensions if ext not in self.bot.extensions]
        loaded = [f"`{ext}`" for ext in self.bot.extensions]

        embed = self.create_cogs_embed(loaded=loaded, unloaded=unloaded)
        embed.title = "Cogs List"

        await ctx.reply(embed=embed, mention_author=False)

    async def send_eval_traceback(self, ctx: Context, *, full: bool) -> None:
        try:
            await ctx.message.add_reaction(Emoji.x)
        except:
            pass

        traceback_str = traceback.format_exc()
        if not full:
            traceback_str = "\n".join(traceback_str.splitlines()[-3:])

        if len(traceback_str) > 2000:
            error_file = self.create_txt_file(traceback_str, large=True)
            await ctx.reply(file=error_file, mention_author=False)
            os.remove(error_file.fp.name)  # type: ignore
        else:
            await ctx.reply(f"```py\n{traceback_str}\n```")

    def create_txt_file(self, content: str, *, large: bool = False) -> discord.File:
        dt = Datetime.get_local_datetime()
        dt_fm = dt.strftime("%y%m%d_%H%M%S")

        filename = f"content_{dt_fm}.txt"
        filepath = f"./log/{filename}"

        if large:
            steps = 2000

            with open(filepath, "w+") as file:
                file.write(content[:2000])

            loops = math.ceil(len(content) / steps)

            for i in range(1, loops):
                start_index = i * steps
                sub_content = content[start_index : start_index + 2000]

                with open(filepath, "a") as file:
                    file.write(sub_content)

        else:
            with open(filepath, "w+") as file:
                file.write(content)

        content_file = discord.File(filepath, filename=filename)
        return content_file

    @commands.command(name="eval")
    async def _eval(self, ctx: Context, *, code: str):
        """Evaluates Python code provided by the user."""

        env = {
            "discord": discord,
            "ctx": ctx,
            "bot": self.bot,
            "channel": ctx.channel,
            "guild": ctx.guild,
            "author": ctx.author,
        }
        env.update(globals())

        code = code.replace("```python", "").replace("```py", "").strip("```").strip("\n")
        exec_func = f"async def __exec_func():\n{textwrap.indent(code, ' ' * 4)}"

        try:
            exec(exec_func, env)
        except:
            return await self.send_eval_traceback(ctx, full=False)

        __exec_func = env["__exec_func"]
        output = StringIO()
        try:
            with redirect_stdout(output):
                ret_val = await __exec_func()
        except:
            return await self.send_eval_traceback(ctx, full=True)

        else:
            value = output.getvalue()
            try:
                await ctx.message.add_reaction(Emoji.white_check_mark)
            except:
                pass

            ret_val = f"{ret_val!r}" if ret_val is not None else None
            content = ret_val or value
            content = content.strip("'")
            if content not in (None, ""):
                content = ast.literal_eval(content)
                content = json.dumps(content, indent=4, sort_keys=True)

                if len(content) > 4096:
                    content_file = self.create_txt_file(content, large=True)
                    await ctx.reply(file=content_file, mention_author=False)
                    os.remove(content_file.fp.name)  # type: ignore

                elif len(content) > 2000:
                    btn_remove = BtnRemoveEmbed(emoji=Emoji.x)
                    view = ui.View().add_item(btn_remove)

                    embed = discord.Embed(color=0xFFFFFF, description=f"```json\n{content}\n```")
                    await ctx.reply(embed=embed, view=view, mention_author=False)

                else:
                    await ctx.reply(f"```json\n{content}\n```", mention_author=False)

    @commands.command(aliases=["s"])
    async def shutdown(self, ctx: Context):
        """Shuts down the bot."""
        await ctx.message.add_reaction(Emoji.white_check_mark)
        await self.bot.close()

    @commands.command()
    async def sync(self, ctx: Context, guild: Optional[discord.Guild] = None):
        if guild is None:
            guild = discord.Object(DEV_TEST_GUILD_ID)  # type: ignore

        await self.bot.tree.sync(guild=guild)
        await ctx.reply("Done!", mention_author=False)

    @commands.command()
    async def bin(self, ctx: Context, dec: int, bit: Optional[int] = None):
        if bit is not None:
            dec &= 1 << bit
            if dec:
                bit = 1
            else:
                bit = 0

            return await ctx.send(f"`{bit}`")

        binary = bin(dec).replace("0b", "")
        binary_fm = str_period_insert(binary, " ", 4)

        await ctx.send(f"```{binary_fm}```")


async def setup(bot: Punchax):
    await bot.add_cog(Admin(bot))
