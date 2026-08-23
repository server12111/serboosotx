"""Publishes long-form documents (User Agreement, Privacy Policy) to Telegra.ph
instead of dumping raw text into a bot message — cleaner reading view, no Telegram
message-length limits, and a real shareable link. Pages are created once (the account
+ page URLs are cached in the settings table) and only re-published when the operator
explicitly asks for a resync via the admin panel.
"""
import json
import logging
import re

import aiohttp

logger = logging.getLogger("boosty.telegraph")

BASE_URL = "https://api.telegra.ph"


class TelegraphError(Exception):
    pass


async def create_account(short_name: str, author_name: str) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{BASE_URL}/createAccount",
            data={"short_name": short_name, "author_name": author_name},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            data = await resp.json()
    if not data.get("ok"):
        raise TelegraphError(f"createAccount failed: {data}")
    return data["result"]["access_token"]


def _text_to_nodes(text: str) -> list:
    """Splits our plain-text docs (blank-line-separated blocks, sections starting
    with "N. Title") into Telegraph's Node format."""
    nodes: list = []
    for block in text.strip().split("\n\n"):
        lines = block.split("\n")
        first = lines[0]
        if re.match(r"^\d+\.\s", first):
            nodes.append({"tag": "h4", "children": [first]})
            rest = "\n".join(lines[1:]).strip()
            if rest:
                nodes.append({"tag": "p", "children": [rest]})
        else:
            nodes.append({"tag": "p", "children": [block]})
    return nodes


async def create_page(access_token: str, title: str, author_name: str, text: str) -> tuple[str, str]:
    """Returns (url, path) — path is needed later to edit_page() in place."""
    nodes = _text_to_nodes(text)
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{BASE_URL}/createPage",
            data={
                "access_token": access_token,
                "title": title,
                "author_name": author_name,
                "content": json.dumps(nodes),
                "return_content": "false",
            },
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            data = await resp.json()
    if not data.get("ok"):
        raise TelegraphError(f"createPage failed: {data}")
    return data["result"]["url"], data["result"]["path"]


async def edit_page(access_token: str, path: str, title: str, author_name: str, text: str) -> str:
    """Updates an existing page in place so a re-publish doesn't orphan the old link."""
    nodes = _text_to_nodes(text)
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{BASE_URL}/editPage/{path}",
            data={
                "access_token": access_token,
                "title": title,
                "author_name": author_name,
                "content": json.dumps(nodes),
                "return_content": "false",
            },
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            data = await resp.json()
    if not data.get("ok"):
        raise TelegraphError(f"editPage failed: {data}")
    return data["result"]["url"]
