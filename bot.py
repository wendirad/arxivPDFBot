import asyncio
import os
import re

import arxiv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile
from decouple import config

TOKEN = config("BOT_TOKEN")

bot = Bot(token=TOKEN)
dp = Dispatcher()
client = arxiv.Client()


def sanitize_filename(title):
    return re.sub(r'[\\/*?:"<>|]', "", title).strip().replace(" ", "_")[:100] + ".pdf"


@dp.message(CommandStart())
async def start(message: types.Message):
    welcome_text = (
        "👋 Welcome to the ArXiv PDF Downloader Bot!\n\n"
        "This bot lets you download PDF files from arXiv. Simply send an arXiv DOI, URL, or paper title, "
        "and I will search for the paper and send you its PDF. You can also send a .bib file and I will process "
        "each entry to download the corresponding PDFs."
    )
    await message.answer(welcome_text)


async def process_download(message: types.Message, query: str):
    progress = "🔍 Checking input...\n"
    progress_msg = await message.answer(progress)

    arxiv_id = None
    doi_match = re.search(r"10\.48550/arXiv\.?([\d.]+)(v\d+)?", query, re.IGNORECASE)
    url_match = re.search(
        r"arxiv\.org/(?:abs|pdf)/([\d.]+)(v\d+)?", query, re.IGNORECASE
    )
    if doi_match:
        arxiv_id = doi_match.group(1)
        progress += f"✅ Detected arXiv ID from DOI: {arxiv_id}\n"
    elif url_match:
        arxiv_id = url_match.group(1)
        progress += f"✅ Detected arXiv ID from URL: {arxiv_id}\n"
    else:
        progress += "ℹ️ No valid arXiv ID found. Using the full text as title search.\n"
    await bot.edit_message_text(
        progress, chat_id=message.chat.id, message_id=progress_msg.message_id
    )

    progress += "🔎 Searching for paper...\n"
    await bot.edit_message_text(
        progress, chat_id=message.chat.id, message_id=progress_msg.message_id
    )
    if arxiv_id:
        search = arxiv.Search(query=f"id:{arxiv_id}", max_results=1)
    else:
        search = arxiv.Search(query=query, max_results=1)
    results = list(client.results(search))
    if not results:
        progress += "❌ No results found for the given input."
        await bot.edit_message_text(
            progress, chat_id=message.chat.id, message_id=progress_msg.message_id
        )
        return

    paper = results[0]
    progress += f'📄 Found paper: "{paper.title}". Starting PDF download...\n'
    await bot.edit_message_text(
        progress, chat_id=message.chat.id, message_id=progress_msg.message_id
    )

    filename = sanitize_filename(paper.title)
    try:
        paper.download_pdf(dirpath=".", filename=filename)
        progress += "⬇️ Download complete. Sending PDF...\n"
        await bot.edit_message_text(
            progress, chat_id=message.chat.id, message_id=progress_msg.message_id
        )
        await message.answer_document(
            FSInputFile(filename), caption=f'PDF for "{paper.title}"'
        )
    except Exception as e:
        progress += f"❌ Error processing file for '{paper.title}': {e}"
        await bot.edit_message_text(
            progress, chat_id=message.chat.id, message_id=progress_msg.message_id
        )
    finally:
        if os.path.exists(filename):
            os.remove(filename)


@dp.message(lambda message: message.text is not None)
async def handle_text(message: types.Message):
    await process_download(message, message.text.strip())


@dp.message(
    lambda message: message.document and message.document.file_name.endswith(".bib")
)
async def handle_bib(message: types.Message):
    progress = ""
    progress_msg = await message.answer("📥 Downloading .bib file...")

    file = await bot.download(message.document.file_id)
    file_path = message.document.file_name
    with open(file_path, "wb") as f:
        f.write(file.read())
    progress += "📄 .bib file downloaded.\n"
    await bot.edit_message_text(
        progress, chat_id=message.chat.id, message_id=progress_msg.message_id
    )

    from bibmanager import bib_manager

    bib = bib_manager.read_file(file_path)
    os.remove(file_path)
    total_entries = len(bib)
    if total_entries == 0:
        progress += "❌ No entries found in the .bib file."
        await bot.edit_message_text(
            progress, chat_id=message.chat.id, message_id=progress_msg.message_id
        )
        return
    progress += (
        f"📚 Found {total_entries} entries in the .bib file. Starting processing...\n"
    )
    await bot.edit_message_text(
        progress, chat_id=message.chat.id, message_id=progress_msg.message_id
    )

    count = 0
    for entry in bib:
        count += 1
        title = entry.title.strip()
        if not title:
            progress += f"[{count}/{total_entries}] ⚠️ No title found for this entry, skipping.\n"
            await bot.edit_message_text(
                progress, chat_id=message.chat.id, message_id=progress_msg.message_id
            )
            continue
        progress += f'[{count}/{total_entries}] 🔎 Searching for paper with title: "{title}"...\n'
        await bot.edit_message_text(
            progress, chat_id=message.chat.id, message_id=progress_msg.message_id
        )
        search = arxiv.Search(query=title, max_results=1)
        results = list(client.results(search))
        if results:
            paper = results[0]
            progress += f'[{count}/{total_entries}] 📄 Found paper: "{paper.title}". Downloading PDF...\n'
            await bot.edit_message_text(
                progress, chat_id=message.chat.id, message_id=progress_msg.message_id
            )
            filename = sanitize_filename(paper.title)
            try:
                paper.download_pdf(dirpath=".", filename=filename)
                progress += (
                    f"[{count}/{total_entries}] ⬇️ Download complete. Sending PDF...\n"
                )
                await bot.edit_message_text(
                    progress,
                    chat_id=message.chat.id,
                    message_id=progress_msg.message_id,
                )
                await message.answer_document(
                    FSInputFile(filename),
                    caption=f'[{count}/{total_entries}] PDF for "{paper.title}"',
                )
            except Exception as e:
                progress += f'[{count}/{total_entries}] ❌ Error processing file for "{paper.title}": {e}\n'
                await bot.edit_message_text(
                    progress,
                    chat_id=message.chat.id,
                    message_id=progress_msg.message_id,
                )
            finally:
                if os.path.exists(filename):
                    os.remove(filename)
        else:
            progress += (
                f'[{count}/{total_entries}] ❌ No results found for "{title}".\n'
            )
            await bot.edit_message_text(
                progress, chat_id=message.chat.id, message_id=progress_msg.message_id
            )


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
