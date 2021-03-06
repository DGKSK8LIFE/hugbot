'''
About this bot
    TODO


Preliminary reading:
    what_is_asyncio.txt
'''

import time
import pytz
import datetime

import os
import random
import platform
import collections

import logging
import contextlib

import aiofiles
import aiohttp
import asyncio
import discord

import hugify


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)8.8s] [%(funcName)16.16s()%(lineno)5.5s] %(message)s",
    # write to stdout AND log file
    handlers=[logging.StreamHandler(), logging.FileHandler(f'{datetime.datetime.now().isoformat()}.log')],
)
logger = logging.getLogger()

client = discord.Client()

is_production = os.environ['PRODUCTION'] == 'True'

MOZHEADER = {'User-Agent': 'Mozilla/5.0'}  # pretend not to be a bot =|

cooldown = collections.defaultdict(int)
RATE_LIMIT = 10
COOLDOWN_MINUTES = 10  # minutes of cooldown when RATE_LIMIT hit


@client.event
async def on_ready():
    g = discord.Game(['I won\'t reply!', 'Use *hug help*!'][is_production])
    await client.change_presence(activity=g)

    logger.info('-' * 20)
    logger.info(f'On  Python version {platform.python_version()}  discord.py version {discord.__version__}')
    logger.info('Environment: %s', ['Testing', 'PRODUCTION!!'][is_production])
    logger.info('My name: %s', client.user)
    logger.info('Servers served: %s', str(len(client.guilds)))
    logger.info('I\'m in!!')
    logger.info('-' * 20)

    heartbeat_channel = client.get_channel(680139339652792324)
    uptime_channel = client.get_channel(680139291208450061)
    cooldown[252145305825443840] = float('-inf')  # immunity for Jan!

    # - Periodically (daily) reset dictionary to prevent memory from growing infinitely
    # - Monitor bot uptime/outages
    while heartbeat_channel and uptime_channel:
        now = datetime.datetime.now()
        await asyncio.sleep(60 - now.second)
        await heartbeat_channel.send("I'm up!")

        if len(cooldown) >= 2:
            logger.info(f'COOLDOWN: {cooldown}')

        if now.hour == 23 and now.minute == 59:
            uptimestamps = [message.created_at.replace(microsecond=0) async for message in heartbeat_channel.history(limit=24*60+10) if message.created_at.day == now.day]
            uptime = len(uptimestamps) / (24 * 60)
            await uptime_channel.send(f'__**Uptime report for {now.isoformat()[:10]}**__:  {100*uptime:.2f}%')
            downtimes = [(earlier, later) for (earlier, later) in zip(uptimestamps[::-1], uptimestamps[-2::-1]) if abs(later - earlier) > datetime.timedelta(minutes=1, seconds=30)]
            for (earlier, later) in downtimes:
                await uptime_channel.send(f'* Went down at {earlier} for {later - earlier} :frowning:')
            if not downtimes:
                await uptime_channel.send('No downtime yay!! :hugging:')
            max_latency = max((timestamp.second, timestamp) for timestamp in uptimestamps if timestamp.second <= 58)
            await uptime_channel.send(f'Maximum latency: {max_latency[0]} seconds at {max_latency[1]}')
            await uptime_channel.send(f'Servers served: {len(client.guilds)}')

    logger.error(f'on_ready concluded unexpectedly. Heartbeat channel {heartbeat_channel} uptime channel {uptime_channel}')


async def cooldown_decrease(author):
    await asyncio.sleep(COOLDOWN_MINUTES*60)
    cooldown[author.id] -= 1
    if cooldown[author.id] == 0:
        del cooldown[author.id]

async def cooldown_increase(author):
    cooldown[author.id] += 1
    asyncio.ensure_future( cooldown_decrease(author) )
    return cooldown[author.id] >= RATE_LIMIT


async def send_message_production(message, msg_str):
    logger.info(f'OUT: {msg_str}')
    channel, author = message.channel, message.author
    msg_str += ('\n' + str(message.author.mention) + ', you are now rate-limited (I will ignore you for a while)') * await cooldown_increase(message.author)
    await channel.send(msg_str)

async def send_file_production(message, msg_str, filename_local, filename_online):
    logger.info(f'OUT: {msg_str}  FILE: {filename_online}')
    channel, author = message.channel, message.author
    msg_str += ('\n' + str(message.author.mention) + ', you are now rate-limited (I will ignore you for a while)') * await cooldown_increase(message.author)
    file = discord.File(filename_local, filename=filename_online)
    await channel.send(msg_str, file=file)

async def send_message_mock(message, msg_str):
    logger.info(f'OUT: {msg_str}')

async def send_file_mock(message, msg_str, filename_local, filename_online):
    logger.info(f'OUT: {msg_str}  FILE: {filename_online}')

send_message = send_message_production if is_production else send_message_mock
send_file = send_file_production if is_production else send_file_mock


def get_avatar_url_gif_or_png(person):
    '''https://stackoverflow.com/questions/54556637
    If no avatar URL is provided, discord will generate an avatar from the discriminator modulo 5
    Pick animated GIF when available and PNG otherwise'''

    try:
        return str(person.avatar_url_as(static_format='png')).rsplit('?', 1)[0]
    except:
        img_url = str(person.avatar_url).replace('webp', 'png').rsplit('?', 1)[0]
        if person.avatar.startswith('a_'):
            img_url = img_url.replace('png', 'gif')

        if not img_url:
            img_url = 'https://cdn.discordapp.com/embed/avatars/' + \
                str(int(person.discriminator) % 5) + '.png'

        return img_url


async def avatar_download_asynchronous(person_list):
    '''Create #num_avatars separate download tasks'''

    async def download(person, i):

        async with aiohttp.ClientSession() as session:
            avatar_url = get_avatar_url_gif_or_png(person)
            async with session.get(avatar_url, headers=MOZHEADER) as resp:
                remote_img = await resp.read()

        avatar_file = f'hug{i}.' + avatar_url.rsplit('.', 1)[1]
        async with aiofiles.open(avatar_file, 'wb') as file:
            await file.write(remote_img)

        return avatar_file

    return await asyncio.gather(*(
        asyncio.ensure_future(download(person, i)) for i, person in enumerate(person_list)
    ))


# ------------------------------------

def only_run_if_activated(function):
    if os.environ['activate_feature_' + function.__name__] != 'True':
        return lambda *a, **b: asyncio.Future()
    return function


@only_run_if_activated
async def execute_code(message, i):
    '''run message as python code (very insecure)'''

    code = message.content[i+1:].replace('```', '').replace('python', '')
    if any(badstr in code for badstr in ['open', 'token', 'os', 'sys', 'exit', 'import', 'subprocess', '_', 'rm']):
        await send_message(client, message, '**You are trying to hack me. Incident reported to FBI CIA**')
        return

    try:
        with io.StringIO() as buf:
            with contextlib.redirect_stdout(buf):
                exec(code, {}, {})
            await send_message(message, buf.getvalue().replace('@', '@​')[:2000])  # escape '@everyone' using zero-width space
    except Exception as e:
        await send_message(message, '**' + repr(e) + '**')


@only_run_if_activated
async def hug(message, message_lower):
    '''hug a person's profile picture'''

    if 'hug help' in message_lower:
        await send_message(message, '''__Hi! I'm a bot who hugs people!__
            - **Huggee**: You can `hug me`, `hug @user`, `hug someone`, and `hug everyone`
            - **Crop**: You can `hug @user square` for their full avatar or `hug @user circle` for a round cutout
            - **Base**: You can `hug @user grin` or `hug @user smile` for different base images
            - **Cooldown**: I will stop responding if you send too many requests
            - **Add me to your server**: <https://discordapp.com/api/oauth2/authorize?client_id=680141163466063960&permissions=34816&scope=bot>
            - **Contact**: See me in the public development server: <https://discord.gg/ZmbBt2A> :slight_smile:''')
        return

    if 'hug attach' in message_lower or 'hug this' in message_lower:
        try:
            url = message.attachments[0].url
            logger.info(f'HUG: {url}')
        except:
            return

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=MOZHEADER) as resp:
                async with aiofiles.open('attach', 'wb') as file:
                    await file.write(await resp.read())

        fn = hugify.hugify_gif_save(['attach'], 'hugged.gif', 180)  # 200
        await send_file(message, '', fn, fn)
        return

    start_time = time.time()

    str_huggees = lambda a: str([str(s) for s in a])
    huggee_list = message.mentions

    if 'hug me' in message_lower:
        huggee_list.append(message.author)

    if 'hug yourself' in message_lower:
        huggee_list.append(client.user)

    if 'hug someone' in message_lower:
        huggee_list.append(random.choice(message.guild.members))

    hug_everyone = message.mention_everyone or 'everyone' in message_lower
    if hug_everyone:
        huggee_list = message.guild.members

    huggee_list = list(set(huggee_list))
    random.shuffle(huggee_list)
    huggee_list = huggee_list[:3]

    logger.info(f'HUG: {str_huggees(message.mentions)} {"@everyone" * hug_everyone}')

    if not huggee_list:
        return

    crop_mode = 'circle' if 'circle' in message_lower else 'square'
    base_mode = 'grin'   if 'grin'   in message_lower else 'smile'

    with message.channel.typing():

        in_filenames = await avatar_download_asynchronous(huggee_list)

        logger.info(f'Done downloading t={time.time() - start_time}')
        logger.info(f'{in_filenames}')

        reply = 'Please refrain from mentioning everyone, use "hug everyone" (no @) instead' * message.mention_everyone

        fn = hugify.hugify_gif_save(in_filenames, 'hugged.gif', 180, base_mode, crop_mode)
        await send_file(message, reply, fn, fn)
        # await send_file(message, reply, fn, 'hugged ' + str_huggees(huggee_list) + '.gif')

        logger.info(f'Done t={time.time() - start_time}')


@client.event
async def on_message(message):

    # don't respond to own messages
    if message.author == client.user:
        return

    logger.info(f'IN: [{str(message.guild): <16.16} #{str(message.channel): <16.16} {message.author.id} @{str(message.author): <18.18}]: {message.content}')

    # don't respond to bots
    if message.author.bot:
        logger.info(f'INTERNAL: Message by bot {message.author} -> message ignored')
        return

    # rate-limit spammers:  allow RATE_LIMIT messages per COOLDOWN_MINUTES minutes
    if cooldown.get(message.author.id, 0) >= RATE_LIMIT:
        logger.info(f'INTERNAL: Message by {message.author} who is rate limited -> message ignored')
        return


    # await send_message_production(client, message, 'I can still respond to your messages!')
    # reply = await client.wait_for_message(timeout=10)
    # if 'shut up' in reply.content:  await send_message_production(client, message, 'no u')


    # # remind to go to bed
    # if datetime.datetime.now(tz=pytz.timezone('CET')).hour < 7:
    #     await send_message(client, message, "Well we had a great day but it's time to go to bed everyone! :hugging:")
    #     # await message.channel.send(str(datetime.datetime.now(tz=pytz.timezone('CET'))))


    message_lower = message.content.lower()
    i = message.content.find('\n')
    if '```python' in message_lower[:i]:
        await execute_code(message, i)


    # reverse input
    if 'revers' in message_lower:
        await send_message(message, message.content[::-1].replace('@', '@​'))  # escape '@everyone' using zero-width space

    if 'good bot' == message_lower:
        await send_message(message, 'uwu')

    if 'uh' + '-' * (len(message_lower) - 2) == message_lower:
        await send_message(message, message_lower + '-')

    # hugify!! ^_^
    if message_lower.startswith('hug'):
        await hug(message, message_lower)


client.run(os.environ['DISCORD_BOT_SECRET'])
