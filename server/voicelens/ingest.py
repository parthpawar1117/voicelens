"""Message ingestion (not implemented yet)."""


async def to_inbox_item(message, *, chat_name, transcribe):
    raise NotImplementedError


def is_watched(chat_id, watched):
    raise NotImplementedError


def load_watched(path, my_id):
    raise NotImplementedError
