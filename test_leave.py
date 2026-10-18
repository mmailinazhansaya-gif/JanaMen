import tempfile,threading,unittest,urllib.error,json
from pathlib import Path
from datetime import datetime,timedelta
import server
from test_mvp import Client
class Leave(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();server.DB=Path(self.temp.name)/'leave.sqlite3';server.init_db()
  self.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler);threading.Thread(target=self.http.serve_forever,daemon=True).start()
  base='http://127.0.0.1:'+str(self.http.server_port)
  self.clients={k:Client(base,k) for k in ('employee','manager','hr','director','hr2','colleague')}
 def tearDown(self):self.http.shutdown();self.http.server_close();self.temp.cleanup()
 def data(self,kind='vacation',offset=200):
  day=(datetime.now(server.TZ).date()+timedelta(days=offset)).isoformat()
  return {'type':kind,'start_date':day,'end_date':day,'comment':'Тест цепочки'}
 def denied(self,fn,status):
  with self.assertRaises(urllib.error.HTTPError) as err:fn()
  self.assertEqual(err.exception.code,status)
 def decide(self,who,rid,status='approved',comment='Решение'):
  return self.clients[who].call(f'/requests/{rid}/decision','POST',{'status':status,'comment':comment})
 def test_only_current_reviewer_notified_and_final_balance(self):
  a=self.clients['employee'];h=self.clients['hr'];m=self.clients['manager'];before=a.call('/me')['user']
  rid=a.call('/requests','POST',self.data())['id']
  self.assertFalse(any(n['kind']=='request' and n['target_id']==rid for n in h.call('/notifications')))
  self.assertTrue(any(n['kind']=='request' and n['target_id']==rid for n in m.call('/notifications')))
  self.denied(lambda:self.decide('hr',rid),403)
  self.denied(lambda:self.decide('hr2',rid),403)
  self.decide('manager',rid)
  self.assertEqual(a.call('/requests/'+str(rid))['current_approver']['user_id'],3)
  self.assertEqual(a.call('/me')['user']['vacation_days'],before['vacation_days'])
  self.assertTrue(any(n['kind']=='request' and n['target_id']==rid for n in h.call('/notifications')))
  self.denied(lambda:self.decide('manager',rid),403)
  self.assertFalse(any(n['title']=='Ваш отпуск согласован' and n['target_id']==rid for n in a.call('/notifications')))
  self.decide('hr',rid);self.denied(lambda:self.decide('hr',rid),409)
  self.assertEqual(a.call('/me')['user']['vacation_days'],before['vacation_days']-1)
  self.assertEqual(a.call('/requests/'+str(rid))['status'],'approved')
 def test_return_revise_restarts_all_steps(self):
  a=self.clients['employee'];before=a.call('/me')['user']['available_days'];rid=a.call('/requests','POST',self.data())['id']
  self.decide('manager',rid);self.denied(lambda:self.decide('hr',rid,'returned',''),400)
  self.decide('hr',rid,'returned','Уточните даты')
  self.assertEqual(a.call('/me')['user']['available_days'],before)
  self.denied(lambda:self.clients['manager'].call(f'/requests/{rid}/resubmit','POST',self.data(offset=210)),403)
  a.call(f'/requests/{rid}/resubmit','POST',self.data(offset=210))
  r=a.call('/requests/'+str(rid));self.assertEqual(r['stage_index'],0);self.assertTrue(all(x['status']=='waiting' for x in r['route']))
  self.assertEqual(len(r['history']),4);self.denied(lambda:self.decide('hr',rid),403)
  self.decide('manager',rid,'rejected','Даты не подходят')
  self.assertTrue(a.call('/requests/'+str(rid))['can_edit'])
  a.call(f'/requests/{rid}/resubmit','POST',self.data(offset=211));self.decide('manager',rid);self.decide('hr',rid)
 def test_every_role_and_leave_type(self):
  for login,first,last in [('manager','director','hr'),('hr','director','hr2'),('director','manager','hr'),('hr2','director','hr'),('colleague','director','hr')]:
   c=self.clients[login];before=c.call('/me')['user']['vacation_days']
   for offset,kind in enumerate(('unpaid','study','social')):
    rid=c.call('/requests','POST',self.data(kind,250+offset))['id']
    self.denied(lambda:self.decide(login,rid),403)
    self.decide(first,rid);self.decide(last,rid)
   self.assertEqual(c.call('/me')['user']['vacation_days'],before)
 def test_migration_and_restart_preserve_history(self):
  a=self.clients['employee'];rid=a.call('/requests','POST',self.data())['id'];self.decide('manager',rid)
  r=a.call('/requests/'+str(rid));server.init_db();self.assertEqual(a.call('/requests/'+str(rid)),r)
  self.assertEqual(a.call('/leave-options')['route'][0]['user_id'],2)
if __name__=='__main__':unittest.main()
