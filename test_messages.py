"""Demo conversations, real delivery, read receipts and private chat boundaries."""
import json
import tempfile
import threading
import unittest
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
import server
import demo_data
from test_mvp import Client


class Messages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        server.DB = Path(cls.temp.name) / 'messages.sqlite3'
        server.init_db()
        cls.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()
        cls.base = 'http://127.0.0.1:' + str(cls.http.server_port)
        cls.employee, cls.manager, cls.hr, cls.other = [Client(cls.base, login) for login in ['employee', 'manager', 'hr', 'colleague']]
        cls.original = cls.employee.call('/messages', 'POST', {'recipient_id': 3, 'body': 'Существующее сообщение до импорта'})['id']
        demo_data.seed_conversations(server)

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.temp.cleanup()

    def test_01_import_preserves_existing_messages_and_orders_by_time(self):
        spec = json.loads((server.ROOT / 'content/demo_messages.json').read_text())
        total = sum(len(c['messages']) for c in spec)
        self.assertEqual(len(spec), 13)
        self.assertEqual(total, 54)
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM direct_messages').fetchone()[0], total + 1)
            original = db.execute('SELECT * FROM direct_messages WHERE id=?', (self.original,)).fetchone()
            self.assertEqual(original['body'], 'Существующее сообщение до импорта')
            self.assertIsNone(original['read_at'])
            self.assertEqual(db.execute('SELECT count(*) FROM direct_messages WHERE read_at IS NULL').fetchone()[0], 1)
        # History was inserted later but must not hide the existing latest message.
        contact = self.hr.call('/messages/contacts')[0]
        self.assertEqual(contact['id'], 1)
        self.assertEqual(contact['last_message']['id'], self.original)
        self.assertEqual(contact['unread'], 1)
        conversation = self.employee.call('/messages/3')
        self.assertEqual(conversation[-1]['id'], self.original)
        self.assertEqual(len(conversation), 7)
        for client in [self.employee, self.manager, self.hr]:
            self.assertGreaterEqual(len([c for c in client.call('/messages/contacts') if c['last_message']]), 4)
        demo_data.seed_conversations(server)
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM direct_messages').fetchone()[0], total + 1)
            self.assertIsNone(db.execute('SELECT read_at FROM direct_messages WHERE id=?', (self.original,)).fetchone()[0])
        # Importing read history creates no fake new-message alerts.
        self.assertEqual(len([n for n in self.hr.call('/notifications') if n['kind'] == 'message']), 1)

    def test_02_real_message_delivers_to_hr_tab_and_marks_read(self):
        # Both accounts use the same browser cookie jar, with per-tab tokens.
        browser = self.employee.http
        sessions = {}
        for login in ['employee', 'hr']:
            req = urllib.request.Request(self.base+'/api/login', data=json.dumps({'login': login, 'password': server.DEMO_PASSWORDS[login], 'tab_scoped': True}).encode(), headers={'Content-Type': 'application/json'})
            with browser.open(req) as response:
                sessions[login] = json.load(response)
        def call(login, path, data=None):
            session = sessions[login]
            req = urllib.request.Request(self.base+'/api'+path, data=json.dumps(data).encode() if data is not None else None,
                headers={'Content-Type': 'application/json', 'Authorization': 'Bearer '+session['token'], 'X-CSRF-Token': session['csrf']})
            with browser.open(req) as response:
                return json.load(response)
        text = 'Аружан, прошу подобрать дополнительное обучение по сложным обращениям.'
        mid = call('employee', '/messages', {'recipient_id': 3, 'body': text})['id']
        contact = call('hr', '/messages/contacts')[0]
        self.assertEqual(contact['id'], 1)
        self.assertEqual(contact['last_message']['id'], mid)
        self.assertGreater(contact['unread'], 0)
        notice = next(n for n in call('hr', '/notifications') if n['kind'] == 'message' and text in n['body'])
        self.assertFalse(notice['is_read'])
        self.assertEqual(notice['target_id'], 1)
        self.assertFalse(next(m for m in call('employee', '/messages/3') if m['id'] == mid)['read_at'])
        received = call('hr', '/messages/1')
        self.assertEqual(received[-1]['id'], mid)
        self.assertTrue(next(m for m in call('employee', '/messages/3') if m['id'] == mid)['read_at'])
        self.assertEqual(next(c for c in call('hr', '/messages/contacts') if c['id'] == 1)['unread'], 0)
        self.assertTrue(next(n for n in call('hr', '/notifications') if n['id'] == notice['id'])['is_read'])
        self.assertFalse(any(text in n['body'] for n in self.manager.call('/notifications')))

    def test_03_every_role_sees_only_its_own_conversations(self):
        for client, own in [(self.employee, 1), (self.manager, 2), (self.hr, 3), (self.other, 4)]:
            peer = 3 if own != 3 else 2
            messages = client.call('/messages/' + str(peer))
            self.assertTrue(all({m['sender_id'], m['recipient_id']} == {own, peer} for m in messages))
        # HR is not granted a backdoor into an employee's conversation with a manager.
        manager_chat = self.hr.call('/messages/2')
        self.assertFalse(any(m['sender_id'] == 1 or m['recipient_id'] == 1 for m in manager_chat))

    def test_04_latest_messages_are_not_lost_in_long_history(self):
        with server.connect() as db:
            start = datetime.now(server.TZ) - timedelta(days=1)
            for i in range(310):
                db.execute('INSERT INTO direct_messages(sender_id,recipient_id,body,created_at,read_at) VALUES(4,11,?,?,?)',
                           (f'Проверка длинной истории {i}', (start+timedelta(seconds=i)).isoformat(), server.now()))
        messages = self.other.call('/messages/11')
        self.assertEqual(len(messages), 300)
        self.assertEqual(messages[0]['body'], 'Проверка длинной истории 10')
        self.assertEqual(messages[-1]['body'], 'Проверка длинной истории 309')


if __name__ == '__main__':
    unittest.main(verbosity=2)
