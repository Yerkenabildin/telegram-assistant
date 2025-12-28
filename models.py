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


class Settings(Model):
    def __init__(self, id=None):
        Model.__init__(self, id, foreign_keys=True)

    def tablename(self):
        return 'settings'

    def columns(self):
        return [
            {
                'name': 'key',
                'type': 'TEXT'
            },
            {
                'name': 'value',
                'type': 'TEXT'
            }
        ]

    @staticmethod
    def get(key):
        setting = Settings().selectOne(SQL().WHERE('key', '=', key))
        return setting.value if setting else None

    @staticmethod
    def set(key, value):
        setting = Settings().selectOne(SQL().WHERE('key', '=', key))
        if setting is None:
            setting = Settings()
        setting.key = key
        setting.value = value
        setting.save()

    @staticmethod
    def get_settings_chat_id():
        value = Settings.get('settings_chat_id')
        return int(value) if value else None

    @staticmethod
    def set_settings_chat_id(chat_id):
        if chat_id is None:
            setting = Settings().selectOne(SQL().WHERE('key', '=', 'settings_chat_id'))
            if setting:
                setting.delete()
        else:
            Settings.set('settings_chat_id', str(chat_id))
