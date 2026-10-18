"""Portable fictional showcase seeding; standard library, bundled demo PDFs.

Migration markers preserve existing user uploads, progress and records. This
runs from the CLI on normal startup; API test fixtures can still use init_db().
"""
import io
import json
import zipfile
from datetime import datetime, timedelta
from xml.sax.saxutils import escape

PROJECTS={1:('Работа с обращениями','Подготовила ответы на частые вопросы клиентов и шаблоны сопровождения доставки.'),2:('Организация филиала','Составил график команды и порядок передачи задач между сменами.'),3:('Адаптация сотрудников','Подготовила чек-лист первого рабочего дня и маршрут согласования кадровых заявок.'),4:('Складские операции','Разработал памятку проверки отправлений и передачи посылок в доставку.'),5:('Поддержка клиентов','Собрал примеры сложных обращений и предложил понятные варианты ответов.'),6:('Координация доставки','Подготовила таблицу контрольных точек доставки и порядок информирования клиента.'),7:('Аналитика процессов','Составил обзор времени обработки обращений и предложения по сокращению задержек.'),8:('Контроль качества','Разработала чек-лист проверки качества ответов и разбор типовых ошибок.'),9:('Обучение команды','Подготовил сценарии практических занятий и памятку наставника для новых коллег.'),10:('Развитие компании','Подготовил план развития филиала и критерии оценки командных результатов.'),11:('Кадровое сопровождение','Собрала памятку по оформлению отпусков и проверке комплектности документов.')}

def seed_showcase(server):
 with server.connect() as c:
  if c.execute("SELECT 1 FROM app_migrations WHERE name='showcase_v1'").fetchone():print('Showcase already present');return
  people=server.rows(c,'SELECT * FROM users ORDER BY id');folder=server.ROOT/'content/showcase'
  for person in people:
   uid=person['id'];stamp=(datetime.now(server.TZ)-timedelta(days=20+uid)).isoformat(timespec='seconds')
   for kind,category,title in [('portfolio','Портфолио','Портфолио сотрудника'),('work','Рабочий материал',PROJECTS[uid][0])]:
    filename=f'{kind}-{uid}.pdf';data=(folder/filename).read_bytes()
    c.execute('INSERT INTO employee_documents(user_id,title,category,filename,mime,size,content,created_at) VALUES(?,?,?,?,?,?,?,?)',(uid,title,category,filename,'application/pdf',len(data),data,stamp))
   # Historical sample course completions: preserve any existing attempts and awards.
   for cid in ([1,2] if uid==1 or uid%3!=1 else [1]):
    old=c.execute('SELECT * FROM enrollments WHERE user_id=? AND course_id=?',(uid,cid)).fetchone()
    if old and (old['completed_at'] or old['completed_lessons']!='[]'):continue
    lessons=json.loads(c.execute('SELECT lessons FROM courses WHERE id=?',(cid,)).fetchone()[0]);score=100
    c.execute('INSERT INTO enrollments(user_id,course_id,assigned_by,completed_lessons,score,completed_at,assigned_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id,course_id) DO UPDATE SET completed_lessons=excluded.completed_lessons,score=excluded.score,completed_at=excluded.completed_at',(uid,cid,3,json.dumps(list(range(len(lessons)))),score,stamp,stamp))
    c.execute('INSERT OR IGNORE INTO xp_awards VALUES(?,?,?,?,?)',(uid,cid,100,'Первый шаг' if cid==1 else 'Безопасная работа',stamp))
    server.academy.award(c,uid,cid,'test',server.now)
   for i,status in enumerate(('approved','rejected','returned')):
    day=(datetime.now(server.TZ).date()-timedelta(days=180-uid*3-i*8));end=day+timedelta(days=1)
    kind=('vacation','unpaid','study')[i];route=server.leave_route(c,person)
    route[0].update(status='approved',decided_at=stamp,comment='Передано в HR')
    route[1].update(status=status,decided_at=stamp,comment={'approved':'Согласовано','rejected':'Период требует пересмотра','returned':'Уточните даты и комментарий'}[status])
    rid=c.execute('INSERT INTO requests(user_id,type,start_date,end_date,days,comment,status,created_at,updated_at,approval_route,stage_index) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(uid,kind,str(day),str(end),2,'Архивная заявка',status,stamp,stamp,json.dumps(route,ensure_ascii=False),1)).lastrowid
    for who,action,comment in [(uid,'Заявка создана',server.LEAVE_TYPES[kind]),(route[0]['user_id'],'Руководитель: Согласована','Передано в HR'),(route[1]['user_id'],'HR: '+server.STATUS[status],route[1]['comment'])]:
     c.execute('INSERT INTO request_history(request_id,actor_id,action,comment,created_at) VALUES(?,?,?,?,?)',(rid,who,action,comment,stamp))
   # Existing annual balances are current balances, not recalculated from sample history.
  for uid in (5,6):
   person=next(p for p in people if p['id']==uid);day=datetime.now(server.TZ).date()+timedelta(days=60+uid);route=server.leave_route(c,person);stage=0 if uid==5 else 1
   if stage:route[0].update(status='approved',decided_at=server.now(),comment='Передано в HR')
   rid=c.execute('INSERT INTO requests(user_id,type,start_date,end_date,days,comment,status,created_at,updated_at,approval_route,stage_index) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(uid,'unpaid',str(day),str(day),1,'Прошу рассмотреть заявку','pending',server.now(),server.now(),json.dumps(route),stage)).lastrowid
   server.history(c,rid,uid,'Заявка создана','Без сохранения зарплаты')
   if stage:server.history(c,rid,route[0]['user_id'],'Руководитель: Согласована','Передано в HR')
   server.notify(c,route[stage]['user_id'],'Новая заявка на согласование',person['name'],'request',rid)
  c.execute("INSERT INTO app_migrations VALUES('showcase_v1')")
  print('Added',len(people)*2,'PDF documents;',len(people)*3+2,'leave examples')


def docx(title, person, lines):
    """Small valid Word document, readable without system fonts or generators."""
    paragraphs = [title, person['name'], person['position'], *lines,
                  'Вымышленный материал для демонстрации. Не официальный документ Jana Post.']
    document = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + ''.join('<w:p><w:r><w:t>' + escape(t) + '</w:t></w:r></w:p>' for t in paragraphs) + '<w:sectPr/></w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr('word/document.xml', document)
    return buf.getvalue()


def seed_office_history(server):
    specs = [
        ('Отчёт за неделю', 'Рабочий материал', ['Обработаны обращения и уточнены сроки.', 'Составлены вопросы для базы знаний.']),
        ('План профессионального развития', 'Портфолио', ['Цель: повысить качество выполнения задач.', 'Практика: разбор задач с наставником.']),
        ('Чек-лист передачи смены', 'Рабочий материал', ['Проверить открытые задачи и ответственных.', 'Передать сроки и статусы следующей смене.']),
        ('Итоги учебного проекта', 'Портфолио', ['Подготовлена памятка для работы команды.', 'Материал передан на обсуждение.']),
    ]
    with server.connect() as c:
        if c.execute("SELECT 1 FROM app_migrations WHERE name='office_history_v2'").fetchone():
            return
        for person in server.rows(c, 'SELECT * FROM users ORDER BY id'):
            uid = person['id']
            for index, (title, category, lines) in enumerate(specs):
                data = docx(title, person, lines)
                c.execute('INSERT INTO employee_documents(user_id,title,category,filename,mime,size,content,created_at) VALUES(?,?,?,?,?,?,?,?)',
                          (uid, title, category, f'demo-{uid}-{index}.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', len(data), data, server.now()))
            # Relative dates keep the example meaningful after the hackathon.
            today = datetime.now(server.TZ).date()
            days = [today - timedelta(days=i) for i in range(1, 20) if (today - timedelta(days=i)).weekday() < 5][:10]
            for day in days:
                start = datetime(day.year, day.month, day.day, 9, uid % 4 * 5, tzinfo=server.TZ)
                work = 7*3600 + (uid*7 + day.day)%50*60
                pause = (35 + (uid + day.day)%25)*60
                end = start + timedelta(seconds=work+pause)
                c.execute('INSERT INTO work_shifts(user_id,started_at,ended_at,work_seconds,break_seconds,break_count) VALUES(?,?,?,?,?,?)',
                          (uid, start.isoformat(), end.isoformat(), work, pause, 2+(uid+day.day)%3))
        c.execute("INSERT INTO app_migrations VALUES('office_history_v2')")


def seed_conversations(server):
    """Import fictional read history once; never overwrite live conversations."""
    with server.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        marker = 'work_conversations_v1'
        if c.execute('SELECT 1 FROM app_migrations WHERE name=?', (marker,)).fetchone():
            return
        conversations = json.loads((server.ROOT / 'content/demo_messages.json').read_text(encoding='utf-8'))
        users = {p['id'] for p in c.execute('SELECT id FROM users')}
        today = datetime.now(server.TZ).replace(hour=9, minute=0, second=0, microsecond=0)
        for index, conversation in enumerate(conversations):
            participants = conversation['people']
            if len(participants) != 2 or len(set(participants)) != 2 or not set(participants) <= users:
                raise ValueError('Invalid demo conversation participants')
            start = today - timedelta(days=1 + index % 5) + timedelta(minutes=index * 17)
            for offset, (sender, text) in enumerate(conversation['messages']):
                if sender not in participants or not isinstance(text, str) or not 1 <= len(text) <= 2000:
                    raise ValueError('Invalid demo message')
                recipient = next(uid for uid in participants if uid != sender)
                stamp = start + timedelta(minutes=offset * 4)
                c.execute('INSERT INTO direct_messages(sender_id,recipient_id,body,created_at,read_at) VALUES(?,?,?,?,?)',
                          (sender, recipient, text, stamp.isoformat(), (stamp + timedelta(minutes=2)).isoformat()))
        c.execute('INSERT INTO app_migrations VALUES(?)', (marker,))


def seed(server):
    seed_showcase(server)
    seed_office_history(server)
    seed_conversations(server)
    import tasks
    with server.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        tasks.seed(c,server.now)
