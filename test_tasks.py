import base64
import concurrent.futures
import tempfile
import threading
import time
import re
import unittest
import urllib.error
import urllib.request
from datetime import datetime,timedelta
from pathlib import Path
import server
import tasks
from test_mvp import Client

class Tasks(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory();server.DB=Path(cls.tmp.name)/'tasks.sqlite3';server.init_db()
  cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler);threading.Thread(target=cls.http.serve_forever,daemon=True).start()
  cls.base='http://127.0.0.1:'+str(cls.http.server_port)
  cls.a=Client(cls.base,'employee');cls.m=Client(cls.base,'manager');cls.h=Client(cls.base,'hr');cls.other=Client(cls.base,'colleague')
 @classmethod
 def tearDownClass(cls):cls.http.shutdown();cls.http.server_close();cls.tmp.cleanup()
 def denied(self,fn,status):
  with self.assertRaises(urllib.error.HTTPError) as e:fn()
  self.assertEqual(e.exception.code,status)
 def body(self,**changes):
  return dict(action='send',title='Проверить обращения',description='Уточнить сроки ответа',assignee_id=1,deadline=(datetime.now(server.TZ)+timedelta(days=1)).isoformat(),**changes)
 def file(self,text='Указания',name='instructions.txt'):return {'filename':name,'content':base64.b64encode(text.encode()).decode()}
 def test_00_all_page_scripts_are_served(self):
  with urllib.request.urlopen(self.base+'/') as r:html=r.read().decode()
  scripts=re.findall(r'<script src="([^"]+)"',html)
  self.assertIn('/tasks.js',scripts)
  for path in scripts:
   with urllib.request.urlopen(self.base+path) as r:
    self.assertEqual(r.status,200);self.assertIn('javascript',r.headers['Content-Type']);self.assertTrue(r.read())
 def test_01_draft_edit_publish_and_recipient_notification(self):
  body=self.body();body.update(action='draft',file=self.file())
  draft=self.m.call('/tasks','POST',body);tid=draft['id']
  self.assertEqual(draft['status'],'draft');self.assertTrue(draft['can_edit'])
  self.assertFalse(any(t['id']==tid for t in self.a.call('/tasks')))
  self.denied(lambda:self.a.call('/tasks/'+str(tid)),403)
  self.denied(lambda:self.h.call('/tasks/'+str(tid)),403)
  body.update(title='Исправленное название',description='Новое описание',file=self.file('Новые указания','new.txt'),version=draft['version'])
  edited=self.m.call('/tasks/'+str(tid),'POST',body)
  self.assertEqual(edited['files'][0]['filename'],'new.txt');self.assertEqual(len(edited['files']),1)
  self.denied(lambda:self.m.call('/tasks/'+str(tid),'POST',body),409)
  body.update(action='send',version=edited['version'],file=None)
  sent=self.m.call('/tasks/'+str(tid),'POST',body)
  self.assertEqual(sent['status'],'active')
  self.assertEqual(self.a.call('/tasks/'+str(tid))['title'],'Исправленное название')
  self.assertEqual(sum(n['kind']=='task' and n['target_id']==tid for n in self.a.call('/notifications')),1)
  self.denied(lambda:self.m.call('/tasks/'+str(tid),'POST',body),409)
 def test_02_result_submission_and_private_download(self):
  body=self.body();body['file']=self.file();t=self.m.call('/tasks','POST',body);tid=t['id']
  url=self.base+f"/api/tasks/{tid}/files/{t['files'][0]['id']}"
  with self.a.http.open(url) as r:self.assertIn('Указания',r.read().decode())
  self.denied(lambda:self.other.http.open(url),403)
  self.denied(lambda:self.m.call(f'/tasks/{tid}/submit','POST',{'result_text':'Сделано'}),403)
  self.denied(lambda:self.a.call(f'/tasks/{tid}/submit','POST',{}),400)
  result=self.a.call(f'/tasks/{tid}/submit','POST',{'result_text':'Проверено 12 обращений','file':self.file('Итоги','result.txt')})
  self.assertEqual(result['status'],'completed');self.assertEqual(len(result['files']),2)
  self.assertEqual(self.m.call('/tasks/'+str(tid))['result_text'],'Проверено 12 обращений')
  self.denied(lambda:self.a.call(f'/tasks/{tid}/submit','POST',{'result_text':'Ещё раз'}),409)
  self.assertEqual(sum(n['kind']=='task' and n['target_id']==tid for n in self.m.call('/notifications')),1)
 def test_03_roles_validation_and_overdue(self):
  self.denied(lambda:self.a.call('/tasks/options'),403)
  self.denied(lambda:self.a.call('/tasks','POST',self.body()),403)
  body=self.body();body['assignee_id']=4
  self.denied(lambda:self.m.call('/tasks','POST',body),403)
  t=self.h.call('/tasks','POST',body)
  self.denied(lambda:self.m.call('/tasks/'+str(t['id'])),403)
  self.denied(lambda:self.other.call('/tasks/'+str(t['id'])+'/submit','POST',{'result_text':'Done'},csrf=False),403)
  body=self.body();body['deadline']=(datetime.now(server.TZ)-timedelta(days=1)).isoformat()
  self.denied(lambda:self.m.call('/tasks','POST',body),400)
  body=self.body();body['file']=self.file('not a PDF','wrong.pdf')
  self.denied(lambda:self.m.call('/tasks','POST',body),400)
  with server.connect() as c:c.execute('UPDATE employee_tasks SET deadline=? WHERE id=?',(time.time()-60,t['id']))
  self.assertEqual(self.other.call('/tasks/'+str(t['id']))['status'],'overdue')
  self.assertEqual(self.other.call('/tasks/'+str(t['id'])+'/submit','POST',{'result_text':'Готово позже срока'})['status'],'completed')
 def test_04_demo_is_repeatable_and_preserves_live_tasks(self):
  with server.connect() as c:
   c.execute('BEGIN IMMEDIATE');before=c.execute('SELECT count(*) FROM employee_tasks').fetchone()[0];tasks.seed(c,server.now)
   after=c.execute('SELECT count(*) FROM employee_tasks').fetchone()[0];self.assertGreater(after,before)
   tasks.seed(c,server.now);self.assertEqual(c.execute('SELECT count(*) FROM employee_tasks').fetchone()[0],after)
  for client in (self.m,self.h):
   counts={k:sum(t['status']==k for t in client.call('/tasks')) for k in ('active','completed','overdue','draft')}
   for k,v in counts.items():self.assertGreaterEqual(v,3,k)
  for task in self.a.call('/tasks'):self.assertEqual(task['assignee_id'],1);self.assertNotEqual(task['status'],'draft')
 def test_05_simultaneous_send_only_notifies_once(self):
  body=self.body();body['action']='draft';draft=self.m.call('/tasks','POST',body)
  body.update(action='send',version=draft['version'])
  def send():
   try:self.m.call('/tasks/'+str(draft['id']),'POST',body);return 200
   except urllib.error.HTTPError as e:return e.code
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:send(),range(2)))
  self.assertEqual(sorted(results),[200,409])
  self.assertEqual(sum(n['kind']=='task' and n['target_id']==draft['id'] for n in self.a.call('/notifications')),1)

if __name__=='__main__':unittest.main()
