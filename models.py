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
            }
        ]

    @staticmethod
    def create(emoji="", msg=None):
        reply = Reply.get_by_emoji(emoji)
        if reply is None:
            reply = Reply()
        reply.emoji = emoji
        reply.message = msg
        reply.save()

    @staticmethod
    def get_by_emoji(emoji):
        return Reply().selectOne(SQL().WHERE('emoji', '=', emoji))
