"""Private document access and server-side video/XP behavior."""
import base64,json,tempfile,threading,unittest,urllib.request,urllib.error,http.cookiejar
from pathlib import Path
import server
from test_mvp import Client

class Features(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();server.DB=Path(cls.temp.name)/'features.sqlite3';server.init_db()
        cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        threading.Thread(target=cls.http.serve_forever,daemon=True).start();cls.base='http://127.0.0.1:'+str(cls.http.server_port)
        cls.employee=Client(cls.base,'employee');cls.manager=Client(cls.base,'manager');cls.hr=Client(cls.base,'hr');cls.other=Client(cls.base,'colleague')
    @classmethod
    def tearDownClass(cls):cls.http.shutdown();cls.http.server_close();cls.temp.cleanup()
    def denied(self,fn,status):
        with self.assertRaises(urllib.error.HTTPError) as e:fn()
        self.assertEqual(e.exception.code,status)
    def upload(self,client):return client.call('/documents','POST',{'title':'Учебный сертификат','category':'Сертификат','filename':'certificate.pdf','content':base64.b64encode(b'%PDF-1.4\nDemo file\n%%EOF').decode(),'user_id':4})['id']
    def test_document_permissions_and_direct_download(self):
        did=self.upload(self.employee)
        self.assertTrue(any(d['id']==did for d in self.employee.call('/people/1/documents')))
        self.assertFalse(any(d['id']==did for d in self.other.call('/people/4/documents')))
        for client in [self.employee,self.manager,self.hr]:
            with client.http.open(self.base+f'/api/documents/{did}/download') as r:
                self.assertTrue(r.read().startswith(b'%PDF-'));self.assertIn('attachment',r.headers['Content-Disposition'])
        self.denied(lambda:self.other.http.open(self.base+f'/api/documents/{did}/download'),403)
        self.denied(lambda:urllib.request.urlopen(self.base+f'/api/documents/{did}/download'),401)
        self.denied(lambda:self.other.call('/people/1/documents'),403)
        self.denied(lambda:self.manager.call('/people/4/documents'),403)
        self.denied(lambda:self.hr.call(f'/documents/{did}/delete','POST',{}),403)
        self.employee.call(f'/documents/{did}/delete','POST',{})
        self.denied(lambda:self.employee.http.open(self.base+f'/api/documents/{did}/download'),404)
    def test_directory_exposes_only_work_card(self):
        people=self.employee.call('/directory');self.assertGreaterEqual(len(people),4)
        for p in people:
            self.assertEqual(set(p),{'id','name','position','department','helps_with','can_documents','is_self'})
            self.assertEqual(p['can_documents'],p['id']==1)
        self.assertFalse(self.manager.call('/people/4')['can_documents'])
        self.assertTrue(self.manager.call('/people/1')['can_documents'])
    def test_avatar_persistence_and_permissions(self):
        defaults=self.employee.call('/avatars')
        self.assertEqual(len(set(p['base'] for p in defaults.values())),len(defaults))
        look={'base':12,'hair':'#334455','skin':'#aabbcc','clothes':'#112233'}
        self.assertEqual(self.employee.call('/avatar','POST',look),look)
        self.assertEqual(self.manager.call('/avatars')['1'],look)
        server.init_db()
        self.assertEqual(Client(self.base,'employee').call('/avatars')['1'],look)
        self.denied(lambda:self.employee.call('/avatar','POST',{**look,'user_id':2}),400)
        self.denied(lambda:self.employee.call('/avatar','POST',{**look,'base':15}),400)
        self.denied(lambda:self.employee.call('/avatar','POST',{**look,'hair':'url(bad)'}),400)
        self.denied(lambda:self.employee.call('/avatar','POST',look,csrf=False),403)
        self.assertEqual(self.manager.call('/avatars')['2'],defaults['2'])
        with self.employee.http.open(self.base+'/avatars.js') as response:self.assertEqual(response.status,200)

    def test_upload_validation(self):
        data={'title':'Test','category':'Другое','filename':'test.pdf','content':base64.b64encode(b'<script>bad</script>').decode()}
        self.denied(lambda:self.employee.call('/documents','POST',data),400)
        data['filename']='../test.pdf';self.denied(lambda:self.employee.call('/documents','POST',data),400)
        data['filename']='test.html';self.denied(lambda:self.employee.call('/documents','POST',data),400)
        data['filename']='test.pdf';data['content']='!!!';self.denied(lambda:self.employee.call('/documents','POST',data),400)
    def test_video_progress_cannot_skip_to_end(self):
        c=self.other.call('/courses/4');length=c['lessons'][0]['duration_seconds']
        self.other.call('/courses/4/video-progress','POST',{'position':0})
        jumped=self.other.call('/courses/4/video-progress','POST',{'position':length})
        self.assertFalse(jumped['ready']);self.assertEqual(jumped['watched'],0)
        self.denied(lambda:self.other.call('/courses/4/lesson','POST',{'index':0}),400)
        self.other.call('/courses/4/video-progress','POST',{'position':0})
        with server.connect() as db:db.execute('UPDATE video_progress SET updated=updated-6 WHERE user_id=4 AND course_id=4')
        valid=self.other.call('/courses/4/video-progress','POST',{'position':5})
        self.assertEqual(valid['watched'],5)
        self.assertEqual(Client(self.base,'colleague').call('/courses/4')['watched'],5)
    def test_xp_requires_pass_and_cannot_repeat(self):
        c=self.employee.call('/courses/3');self.assertEqual(len(c['quiz']),10)
        self.assertTrue(all('correct' not in q for q in c['quiz']))
        with server.connect() as db:
            quiz=json.loads(db.execute('SELECT quiz FROM courses WHERE id=3').fetchone()[0]);seconds=c['lessons'][0]['duration_seconds']
            db.execute('INSERT OR REPLACE INTO video_progress VALUES(1,3,?,?,?)',(seconds,seconds,server.time.time()))
        self.employee.call('/courses/3/lesson','POST',{'index':0})
        before=self.employee.call('/me')['user']['learning']['xp']
        wrong=[(q['correct']+1)%len(q['options']) for q in quiz]
        failed=self.employee.call('/courses/3/quiz','POST',{'answers':wrong});self.assertFalse(failed['passed']);self.assertEqual(failed['xp_earned'],0)
        self.denied(lambda:self.employee.call('/courses/3/quiz','POST',{'answers':wrong}),400)
        self.assertEqual(self.employee.call('/courses/3')['watched'],0)
        with server.connect() as db:db.execute('INSERT OR REPLACE INTO video_progress VALUES(1,3,?,?,?)',(seconds,seconds,server.time.time()))
        self.employee.call('/courses/3/lesson','POST',{'index':0})
        answers=[q['correct'] if i<7 else wrong[i] for i,q in enumerate(quiz)]
        passed=self.employee.call('/courses/3/quiz','POST',{'answers':answers});self.assertTrue(passed['passed']);self.assertEqual(passed['score'],70);self.assertEqual(passed['xp_earned'],100)
        self.denied(lambda:self.employee.call('/courses/3/quiz','POST',{'answers':answers}),409)
        stats=Client(self.base,'employee').call('/me')['user']['learning'];self.assertEqual(stats['xp'],before+100);self.assertEqual(len(stats['badges']),1)
        server.init_db();self.assertEqual(self.employee.call('/me')['user']['learning']['xp'],before+100)
    def test_work_shift_is_saved_and_visible_to_manager(self):
        started=self.employee.call('/presence','POST',{'mode':'work','enter':True})
        self.assertEqual(started['from_location'],'entrance')
        with server.connect() as db:
            db.execute('UPDATE presence SET changed_at=changed_at-3700,arrive_at=arrive_at-3700,work_seconds=3600 WHERE user_id=1')
        pause=self.employee.call('/presence','POST',{'mode':'break','location':'kitchen'})
        with server.connect() as db:
            db.execute('UPDATE presence SET changed_at=changed_at-60,arrive_at=arrive_at-60 WHERE user_id=1')
        resumed=self.employee.call('/presence','POST',{'mode':'work'})
        self.assertAlmostEqual(pause['work_seconds'],resumed['work_seconds'],delta=1)
        self.assertGreaterEqual(resumed['break_seconds'],60)
        with server.connect() as db:
            db.execute('UPDATE presence SET arrive_at=arrive_at-10 WHERE user_id=1')
        ended=self.employee.call('/presence','POST',{'mode':'off'})
        self.assertIsNotNone(ended['completed_shift'])
        self.assertGreaterEqual(ended['completed_shift']['work_seconds'],3600)
        own=self.employee.call('/shifts');managed=self.manager.call('/people/1/shifts')
        self.assertEqual(own[0]['id'],managed[0]['id'])
        self.assertEqual(own[0]['break_count'],1)
        self.denied(lambda:self.other.call('/people/1/shifts'),403)
        self.assertFalse(any(n['kind']=='shift' for n in self.manager.call('/notifications')))
    def test_internal_messages_and_assistant_action(self):
        self.employee.call('/messages','POST',{'recipient_id':2,'body':'Санжар, отчёт готов.'})
        contacts=self.manager.call('/messages/contacts')
        self.assertEqual(contacts[0]['id'],1)
        self.assertGreater(contacts[0]['unread'],0)
        conversation=self.manager.call('/messages/1')
        self.assertEqual(conversation[-1]['body'],'Санжар, отчёт готов.')
        self.assertIsNotNone(conversation[-1]['read_at'])
        self.assertFalse(any(n['kind']=='message' and n['target_id']==1 and not n['is_read'] for n in self.manager.call('/notifications')))
        proposal=self.employee.call('/assistant','POST',{'question':'Напиши Санжару: я закончила обучение'})
        self.assertEqual(proposal['kind'],'confirm_action')
        self.assertEqual(proposal['action']['recipient_id'],2)
        self.assertEqual(proposal['action']['body'],'я закончила обучение')
        sent=self.employee.call('/assistant/action','POST',{'action':'send_message','recipient_id':2,'body':proposal['action']['body']})
        self.assertEqual(sent['kind'],'action_done')
        self.assertEqual(self.manager.call('/messages/1')[-1]['body'],'я закончила обучение')
        self.denied(lambda:self.employee.call('/messages','POST',{'recipient_id':1,'body':'self'}),404)
    def test_assistant_understands_dynamic_topics(self):
        for question,kind in [('Привет','assistant'),('Какие курсы мне пройти?','assistant'),('Покажи моё рабочее время','assistant'),('Как загрузить сертификат?','assistant'),('Как оформить отпуск?','assistant')]:
            result=self.employee.call('/assistant','POST',{'question':question})
            self.assertEqual(result['kind'],kind)
            self.assertGreater(len(result['answer']),20)
        unknown=self.employee.call('/assistant','POST',{'question':'Объясни квантовую гравитацию'})
        self.assertEqual(unknown['kind'],'clarify')
    def test_media_range_and_duration(self):
        for cid in [3,4]:
            c=self.employee.call('/courses/'+str(cid));lesson=c['lessons'][0];self.assertTrue(300<=lesson['duration_seconds']<=360)
            req=urllib.request.Request(self.base+lesson['video'],headers={'Range':'bytes=0-99'})
            with urllib.request.urlopen(req) as r:
                self.assertEqual(r.status,206);self.assertEqual(len(r.read()),100);self.assertEqual(r.headers['Content-Type'],'video/mp4')
            with urllib.request.urlopen(self.base+lesson['captions']) as r:self.assertTrue(r.read().startswith(b'WEBVTT'))

if __name__=='__main__':unittest.main()
