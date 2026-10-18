"""Academy recipient privacy, authored courses and non-farmable learning levels."""
import base64,json,tempfile,threading,unittest,urllib.error,urllib.request
from pathlib import Path
import server
from test_mvp import Client

class Academy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();server.DB=Path(cls.temp.name)/'academy.sqlite3';server.init_db()
        cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        threading.Thread(target=cls.http.serve_forever,daemon=True).start();cls.base='http://127.0.0.1:'+str(cls.http.server_port)
        cls.alina=Client(cls.base,'employee');cls.timur=Client(cls.base,'colleague');cls.manager=Client(cls.base,'manager');cls.hr=Client(cls.base,'hr')
    @classmethod
    def tearDownClass(cls):cls.http.shutdown();cls.http.server_close();cls.temp.cleanup()
    def denied(self,fn,status):
        with self.assertRaises(urllib.error.HTTPError) as error:fn()
        self.assertEqual(error.exception.code,status)
    def folder(self,**kwargs):
        return {'title':'Работа с обращением','description':'Пошаговая инструкция','kind':'folder','target_type':'employee','target_value':'1','files':[{'filename':'instruction.txt','content':base64.b64encode('Инструкция: проверьте номер обращения'.encode()).decode()}],**kwargs}
    def test_private_folder_and_direct_download(self):
        aid=self.hr.call('/academy/assignments','POST',self.folder())['id']
        a=next(a for a in self.alina.call('/academy/assignments') if a['id']==aid);fid=a['files'][0]['id']
        self.assertNotIn(aid,[a['id'] for a in self.timur.call('/academy/assignments')])
        for client in [self.alina,self.hr]:
            with client.http.open(self.base+f'/api/academy/files/{fid}') as response:self.assertIn('Инструкция',response.read().decode())
        self.denied(lambda:self.timur.http.open(self.base+f'/api/academy/files/{fid}'),403)
        self.denied(lambda:self.manager.http.open(self.base+f'/api/academy/files/{fid}'),403)
        self.denied(lambda:self.timur.call(f'/academy/assignments/{aid}/read','POST',{}),403)
        self.alina.call(f'/academy/assignments/{aid}/read','POST',{})
        self.assertFalse(any(not n['is_read'] and n['kind']=='academy_material' and n['target_id']==aid for n in self.alina.call('/notifications')))
        a=next(a for a in self.hr.call('/academy/assignments') if a['id']==aid)
        self.assertTrue(a['recipients'][0]['read_at'])
    def test_hr_permissions_and_recipient_validation(self):
        for client in [self.alina,self.manager]:
            self.denied(lambda:client.call('/academy/options'),403)
            self.denied(lambda:client.call('/academy/assignments','POST',self.folder()),403)
        self.denied(lambda:self.hr.call('/academy/assignments','POST',self.folder(target_value='999')),400)
        self.denied(lambda:self.hr.call('/academy/assignments','POST',self.folder(files=[])),400)
        self.denied(lambda:self.hr.call('/academy/assignments','POST',self.folder(files=[{'filename':'bad.html','content':base64.b64encode(b'<script>').decode()}])),400)
    def test_department_and_position_assignments(self):
        for target,value in [('department','Склад'),('position','Специалист склада')]:
            result=self.hr.call('/academy/assignments','POST',self.folder(target_type=target,target_value=value))
            self.assertEqual(result['recipients'],1)
            self.assertIn(result['id'],[a['id'] for a in self.timur.call('/academy/assignments')])
            self.assertNotIn(result['id'],[a['id'] for a in self.alina.call('/academy/assignments')])
    def test_role_tracks(self):
        alina=self.alina.call('/courses');timur=self.timur.call('/courses');manager=self.manager.call('/courses');hr=self.hr.call('/courses')
        for courses,n in [(alina,4),(timur,4),(manager,5),(hr,4)]:
            self.assertGreaterEqual(sum(bool(c['video']) for c in courses),n)
            self.assertTrue({1,2}.issubset({c['id'] for c in courses}))
        self.assertNotEqual({c['id'] for c in alina},{c['id'] for c in timur})
        self.denied(lambda:self.timur.call('/courses/3'),403)
        self.denied(lambda:self.timur.call('/enroll','POST',{'course_id':3}),403)
    def test_upload_video_course_and_reassignment(self):
        quiz=[{'question':f'Вопрос {i+1}','options':['Правильно','Неверно'],'correct':0} for i in range(10)]
        payload=self.folder(kind='new_course',files=[{'filename':'lesson.mp4','content':base64.b64encode(b'\x00\x00\x00\x18ftypmp42test').decode()}],duration_seconds=300,quiz=quiz)
        result=self.hr.call('/academy/assignments','POST',payload);cid=result['course_id']
        course=self.alina.call(f'/courses/{cid}');self.assertEqual(len(course['quiz']),10);self.assertNotIn('correct',course['quiz'][0])
        video=course['lessons'][0]['video']
        self.denied(lambda:self.timur.http.open(self.base+video),403)
        self.hr.call('/academy/assignments','POST',{'title':'Повторное назначение','description':'','kind':'course','course_id':cid,'target_type':'employee','target_value':'4'})
        with self.timur.http.open(self.base+video) as response:self.assertIn(b'ftyp',response.read())
    def test_levels_failure_restart_no_duplicate_and_no_hr_notices(self):
        cid=4;course=self.alina.call(f'/courses/{cid}');seconds=course['lessons'][0]['duration_seconds'];before=self.alina.call('/me')['user']['learning']['xp'];hr_before=len(self.hr.call('/notifications'))
        with server.connect() as c:
            quiz=json.loads(c.execute('SELECT quiz FROM courses WHERE id=?',(cid,)).fetchone()[0])
            c.execute('INSERT OR REPLACE INTO video_progress VALUES(?,?,?,?,?)',(1,cid,seconds,seconds,server.time.time()))
        self.alina.call(f'/courses/{cid}/lesson','POST',{'index':0})
        self.assertEqual(self.alina.call('/me')['user']['learning']['xp'],before+100)
        wrong=[(q['correct']+1)%len(q['options']) for q in quiz]
        self.alina.call(f'/courses/{cid}/quiz','POST',{'answers':wrong})
        self.assertEqual(self.alina.call(f'/courses/{cid}')['watched'],0)
        self.assertEqual(self.alina.call(f'/courses/{cid}')['completed_lessons'],[])
        self.denied(lambda:self.alina.call(f'/courses/{cid}/quiz','POST',{'answers':[q['correct'] for q in quiz]}),400)
        with server.connect() as c:c.execute('INSERT OR REPLACE INTO video_progress VALUES(?,?,?,?,?)',(1,cid,seconds,seconds,server.time.time()))
        self.alina.call(f'/courses/{cid}/lesson','POST',{'index':0})
        self.assertEqual(self.alina.call('/me')['user']['learning']['xp'],before+100)
        self.alina.call(f'/courses/{cid}/quiz','POST',{'answers':[q['correct'] for q in quiz]})
        self.assertEqual(self.alina.call('/me')['user']['learning']['xp'],before+200)
        self.assertEqual(len(self.hr.call('/notifications')),hr_before)
    def test_level_cap_and_restart_persistence(self):
        with server.connect() as c:
            for cid in range(1,10):
                server.academy.award(c,4,cid,'watch',server.now);server.academy.award(c,4,cid,'test',server.now)
        stats=self.timur.call('/me')['user']['learning'];self.assertEqual(stats['level'],10);self.assertGreater(stats['xp'],1000)
        server.init_db();self.assertEqual(self.timur.call('/me')['user']['learning'],stats)

if __name__=='__main__':unittest.main()
