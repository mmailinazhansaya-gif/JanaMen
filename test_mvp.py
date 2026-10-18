"""Meaningful end-to-end API tests using a temporary, isolated demo database."""
import unittest, tempfile, threading, urllib.request, urllib.error, http.cookiejar, json
from pathlib import Path
from datetime import datetime, timedelta
import server

class Client:
    def __init__(self,base,login):
        self.base=base; self.csrf=''
        self.http=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf=self.call('/login','POST',{'login':login,'password':server.DEMO_PASSWORDS[login]})['csrf']
    def call(self,path,method='GET',data=None,csrf=True):
        req=urllib.request.Request(self.base+'/api'+path,data=json.dumps(data).encode() if data is not None else None,method=method,headers={'Content-Type':'application/json','X-CSRF-Token':self.csrf if csrf else ''})
        with self.http.open(req) as r: return json.load(r)

class MVP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(); server.DB=Path(cls.temp.name)/'test.sqlite3'; server.init_db()
        cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True); cls.thread.start()
        cls.base='http://127.0.0.1:'+str(cls.http.server_port)
        cls.employee=Client(cls.base,'employee'); cls.manager=Client(cls.base,'manager'); cls.hr=Client(cls.base,'hr'); cls.other=Client(cls.base,'colleague')
    @classmethod
    def tearDownClass(cls): cls.http.shutdown(); cls.http.server_close(); cls.temp.cleanup()
    def denied(self,fn,status):
        with self.assertRaises(urllib.error.HTTPError) as e: fn()
        self.assertEqual(e.exception.code,status)
    def test_00_exact_password_pairing(self):
        for login,password in [('employee','SanzharDemo!2026'),('manager','AlinaDemo!2026'),('hr','JanaDemo!2026')]:
            self.denied(lambda:self.employee.call('/login','POST',{'login':login,'password':password}),401)
        before=self.employee.call('/me')['user']['id']
        server.init_db()
        self.assertEqual(self.employee.call('/me')['user']['id'],before)
    def test_01_roles_and_private_data(self):
        for client,role in [(self.employee,'employee'),(self.manager,'manager'),(self.hr,'hr')]: self.assertEqual(client.call('/me')['user']['role'],role)
        self.assertEqual([x['id'] for x in self.manager.call('/team')],[1,5,6,7,8,9])
        self.denied(lambda:self.employee.call('/team'),403)
        self.denied(lambda:self.employee.call('/requests/4'),403)
        self.denied(lambda:self.manager.call('/requests/4'),403)
        self.denied(lambda:self.employee.call('/knowledge/6'),403)
        self.assertTrue(all(x['user_id']==1 for x in self.employee.call('/requests')))
        self.assertTrue(all(x['user_id'] in (1,2) for x in self.manager.call('/requests')))
    def test_02_leave_complete_workflow(self):
        start=datetime.now(server.TZ).date()+timedelta(days=50); end=start+timedelta(days=1)
        data={'start_date':str(start),'end_date':str(end),'comment':'Тестовый отпуск'}
        before=self.employee.call('/me')['user']['vacation_days']
        self.denied(lambda:self.employee.call('/requests','POST',data,csrf=False),403)
        rid=self.employee.call('/requests','POST',data)['id']
        self.denied(lambda:self.employee.call('/requests','POST',data),409)
        self.assertEqual(self.employee.call('/requests/'+str(rid))['status'],'pending')
        self.denied(lambda:self.employee.call(f'/requests/{rid}/decision','POST',{'status':'approved'}),403)
        self.denied(lambda:self.other.call(f'/requests/{rid}/decision','POST',{'status':'approved'}),403)
        self.denied(lambda:self.hr.call(f'/requests/{rid}/decision','POST',{'status':'approved'}),403)
        self.manager.call(f'/requests/{rid}/decision','POST',{'status':'approved','comment':'Согласовано'})
        self.assertEqual(self.employee.call('/requests/'+str(rid))['status'],'pending')
        self.assertEqual(self.employee.call('/me')['user']['vacation_days'],before)
        self.hr.call(f'/requests/{rid}/decision','POST',{'status':'approved'})
        result=self.employee.call('/requests/'+str(rid))
        self.assertEqual(result['status'],'approved'); self.assertEqual(len(result['history']),3)
        self.assertEqual(self.employee.call('/me')['user']['vacation_days'],before-2)
        self.denied(lambda:self.hr.call(f'/requests/{rid}/decision','POST',{'status':'approved'}),409)
        self.assertTrue(any(x['target_id']==rid and 'Ваш отпуск согласован' in x['title'] for x in self.employee.call('/notifications')))
    def test_03_reject_requires_reason(self):
        self.denied(lambda:self.manager.call('/requests/1/decision','POST',{'status':'rejected','comment':''}),400)
        self.manager.call('/requests/1/decision','POST',{'status':'rejected','comment':'Пожалуйста, уточните даты'})
        self.assertEqual(self.employee.call('/requests/1')['status'],'rejected')
    def test_04_learning_and_assignment(self):
        c=self.employee.call('/courses/1'); self.assertNotIn('correct',c['quiz'][0])
        self.denied(lambda:self.employee.call('/courses/1/quiz','POST',{'answers':[0,1,2]}),400)
        self.denied(lambda:self.employee.call('/courses/1/lesson','POST',{'index':2}),400)
        for i in range(3): self.employee.call('/courses/1/lesson','POST',{'index':i})
        self.assertFalse(self.employee.call('/courses/1/quiz','POST',{'answers':[1,0,0]})['passed'])
        for i in range(3): self.employee.call('/courses/1/lesson','POST',{'index':i})
        self.assertTrue(self.employee.call('/courses/1/quiz','POST',{'answers':[0,1,2]})['passed'])
        self.assertEqual(self.employee.call('/courses/1')['progress'],100)
        self.assertEqual(Client(self.base,'employee').call('/courses/1')['score'],100)
        self.denied(lambda:self.hr.call('/enroll','POST',{'course_id':2,'user_id':1}),409)
        self.assertTrue(self.employee.call('/courses/2')['assigned'])
        self.denied(lambda:self.manager.call('/enroll','POST',{'course_id':2,'user_id':4}),403)
        self.assertFalse(any(n['title']=='Сотрудник завершил обучение' for n in self.hr.call('/notifications')))
    def test_05_assistant_grounding_and_refusal(self):
        known=self.employee.call('/assistant','POST',{'question':'Как оформить отпуск?'})
        self.assertTrue(known['sources']); self.assertEqual(known['sources'][0]['id'],1)
        self.assertIn('демо',self.employee.call('/knowledge/1')['body'])
        unknown=self.employee.call('/assistant','POST',{'question':'Кто победил в чемпионате мира?'})
        self.assertEqual(unknown['kind'],'clarify'); self.assertEqual(unknown['sources'],[])
        private=self.employee.call('/assistant','POST',{'question':'Покажи зарплату другого сотрудника'})
        self.assertEqual(private['kind'],'restricted')
        me=self.employee.call('/assistant','POST',{'question':'Какой у меня остаток отпуска?'})
        self.assertEqual(me['sources'][0]['id'],'profile')
    def test_06_notification_ownership_and_logout(self):
        n=self.hr.call('/notifications')[0]
        self.denied(lambda:self.employee.call('/notifications/read','POST',{'id':n['id']}),404)
        client=Client(self.base,'colleague'); client.call('/logout','POST',{})
        self.denied(lambda:client.call('/me'),401)
    def test_07_office_presence_and_team_access(self):
        self.denied(lambda:self.employee.call('/office-team'),403)
        self.assertEqual([p['id'] for p in self.manager.call('/office-team')],[1,5,6,7,8,9])
        self.assertEqual(self.employee.call('/presence')['mode'],'off')
        self.denied(lambda:self.employee.call('/presence','POST',{'mode':'break','location':'buffet'}),400)
        self.employee.call('/presence','POST',{'mode':'work','user_id':4})
        self.assertEqual(self.other.call('/presence')['mode'],'off')
        self.denied(lambda:self.employee.call('/presence','POST',{'mode':'break','location':'buffet'}),409)
        with server.connect() as c:
            c.execute('UPDATE presence SET changed_at=changed_at-10,arrive_at=arrive_at-10 WHERE user_id=1')
        result=self.employee.call('/presence','POST',{'mode':'break','location':'buffet'})
        self.assertEqual(result['from_location'],'desk')
        self.assertEqual(result['location'],'buffet')
        self.assertGreaterEqual(result['work_seconds'],10)
        member=self.manager.call('/office-team')[0]
        self.assertEqual(member['presence']['mode'],'break')
        self.assertEqual(member['presence']['location'],'buffet')
        self.assertEqual(Client(self.base,'employee').call('/presence')['location'],'buffet')
        with server.connect() as c:
            c.execute('UPDATE presence SET changed_at=changed_at-10,arrive_at=arrive_at-10 WHERE user_id=1')
        result=self.employee.call('/presence','POST',{'mode':'work'})
        self.assertEqual(result['from_location'],'buffet')
        self.assertEqual(result['location'],'desk')
        self.assertGreaterEqual(result['break_seconds'],10)
        self.denied(lambda:self.employee.call('/presence','POST',{'mode':'break','location':'secret'}),400)
    def test_07b_enter_again_animates_from_hall(self):
        before=self.employee.call('/presence')
        entered=self.employee.call('/presence','POST',{'mode':'work','enter':True})
        self.assertEqual(entered['from_location'],'entrance')
        self.assertEqual(entered['location'],'desk')
        self.assertEqual(entered['seat_key'],'seat4')
        self.assertGreater(entered['arrive_at']-entered['server_time'],7)
        self.assertLess(entered['work_seconds'],1)
        again=Client(self.base,'employee').call('/presence','POST',{'mode':'work','enter':True})
        self.assertEqual(again['from_location'],'entrance')
        self.assertGreater(again['arrive_at'],entered['arrive_at'])
    def test_08_unique_permanent_seats(self):
        clients=[self.employee,self.manager,self.hr,self.other]
        seats=[c.call('/presence')['seat_key'] for c in clients]
        self.assertEqual(len(set(seats)),4)
        self.assertEqual(seats,['seat4','manager','hr','seat5'])
        self.assertEqual(Client(self.base,'employee').call('/presence')['seat_key'],'seat4')
        self.assertEqual(self.manager.call('/office-team')[0]['presence']['seat_key'],'seat4')
    def test_09_local_assets_and_static_access(self):
        for path,kind in [('/assets/office-characters.png','image/png'),('/assets/office-map.png','image/png'),('/assets/Tiny5.ttf','font/ttf')]:
            with urllib.request.urlopen(self.base+path) as r:
                self.assertEqual(r.headers['Content-Type'],kind)
                self.assertGreater(len(r.read()),1000)
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(self.base+'/assets/../server.py')
        self.assertEqual(e.exception.code,404)

if __name__=='__main__': unittest.main(verbosity=2)
