import json

from sqlitemodel import Model, Database, SQL
from telethon.extensions import BinaryReader
from telethon.tl.types import Message, PeerChat

Database.DB_FILE = './storage/database.db'


class Reply(Model):
    def __init__(self, id=None):
        Model.__init__(self, id, foreign_keys=True)

    def tablename(self):
        return 'replays'

    @property
    def message(self):
        reader = BinaryReader(self._message)
        reader.read_int()
        return Message.from_reader(reader)

    @message.setter
    def message(self, value):
        self._message = value._bytes()

    def columns(self):
        return [
            {
                'name': 'emoji',
                'type': 'TEXT'
            },
            {
                'name': '_message',
                'type': 'TEXT'
            },
            {
                'name': 'chat_id',
                'type': 'INTEGER'
            }
        ]

    @staticmethod
    def create(emoji="", msg=None, chat_id=None):
        reply = Reply.get_by_emoji_and_chat(emoji, chat_id)
        if reply is None:
            reply = Reply()
        reply.emoji = emoji
        reply.message = msg
        reply.chat_id = chat_id
        reply.save()

    @staticmethod
    def get_by_emoji(emoji):
        return Reply().selectOne(SQL().WHERE('emoji', '=', emoji).AND('chat_id', 'IS', None))

    @staticmethod
    def get_by_emoji_and_chat(emoji, chat_id=None):
        if chat_id is None:
            return Reply().selectOne(SQL().WHERE('emoji', '=', emoji).AND('chat_id', 'IS', None))
        return Reply().selectOne(SQL().WHERE('emoji', '=', emoji).AND('chat_id', '=', chat_id))

    @staticmethod
    def get_reply_for_context(emoji, chat_id=None):
        """Get reply: first check chat-specific, then fall back to global"""
        if chat_id:
            chat_reply = Reply.get_by_emoji_and_chat(emoji, chat_id)
            if chat_reply:
                return chat_reply
        return Reply.get_by_emoji(emoji)
