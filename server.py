#!/usr/bin/env python3
"""JanaMen hackathon MVP. Python standard library, SQLite, server-side RBAC."""
import os, json, sqlite3, secrets, hashlib, hmac, time, argparse, re, base64, binascii, io, zipfile, difflib
from urllib.parse import quote
from pathlib import Path
from datetime import datetime, date, timedelta, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get('JANAMEN_DB', str(ROOT / 'data' / 'janamen.sqlite3')))
TZ = timezone(timedelta(hours=5))
ROLES = {'employee': 'Сотрудник', 'manager': 'Руководитель', 'hr': 'HR / администратор'}
STATUS = {'pending': 'На согласовании', 'approved': 'Согласована', 'rejected': 'Отклонена', 'returned':'На доработке'}

def now(): return datetime.now(TZ).isoformat(timespec='seconds')
def connect():
    c = sqlite3.connect(DB, timeout=20)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c
def rows(c, sql, args=()): return [dict(r) for r in c.execute(sql, args).fetchall()]
def password_hash(password, salt): return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 150000).hex()
def notify(c, uid, title, body, kind, target):
    c.execute('INSERT INTO notifications(user_id,title,body,kind,target_id,created_at) VALUES(?,?,?,?,?,?)', (uid,title,body,kind,target,now()))
def history(c, rid, uid, action, comment=''):
    c.execute('INSERT INTO request_history(request_id,actor_id,action,comment,created_at) VALUES(?,?,?,?,?)', (rid,uid,action,comment,now()))

DEMO_PASSWORDS = {'employee':'AlinaDemo!2026','manager':'SanzharDemo!2026','hr':'HRDemo!2026','colleague':'TimurDemo!2026','director':'DirectorDemo!2026','hr2':'HR2Demo!2026'}

def seed_branch_people(c):
    """Add a small, messageable demo branch without replacing existing demo data."""
    people = [
        (5,'arman.demo','Арман Омаров','Специалист поддержки','Клиентский сервис',2,'seat0'),
        (6,'diana.demo','Диана Ахметова','Координатор доставки','Операционный отдел',2,'seat1'),
        (7,'daniyar.demo','Данияр Нурланов','Аналитик процессов','Операционный отдел',2,'seat2'),
        (8,'zhanna.demo','Жанна Ибраева','Специалист по качеству','Клиентский сервис',2,'seat3'),
        (9,'marat.demo','Марат Сериков','Наставник Academy','Обучение',2,'study0'),
    ]
    for uid,login,name,position,department,manager,seat in people:
        if c.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone(): continue
        salt=secrets.token_hex(16)
        password=secrets.token_urlsafe(32)
        c.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                  (uid,login,name,'employee','Jana Post · демо',position,department,manager,'2025-02-03',18,salt,password_hash(password,salt)))
        c.execute('INSERT OR IGNORE INTO office_seats VALUES(?,?)',(uid,seat))

def migrate_demo_passwords(c):
    c.execute('CREATE TABLE IF NOT EXISTS app_migrations(name TEXT PRIMARY KEY)')
    if c.execute("SELECT 1 FROM app_migrations WHERE name='distinct_demo_passwords_v1'").fetchone(): return
    for login,password in DEMO_PASSWORDS.items():
        salt=secrets.token_hex(16)
        c.execute('UPDATE users SET salt=?,password_hash=? WHERE login=?',(salt,password_hash(password,salt),login))
    c.execute('DELETE FROM sessions')
    c.execute("INSERT INTO app_migrations VALUES('distinct_demo_passwords_v1')")

def init_db_base():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with connect() as c:
        c.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,login TEXT UNIQUE,name TEXT,role TEXT,company TEXT,position TEXT,department TEXT,manager_id INTEGER REFERENCES users(id),hired_at TEXT,vacation_days INTEGER,salt TEXT,password_hash TEXT);
        CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER REFERENCES users(id),csrf TEXT,expires REAL);
        CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER REFERENCES users(id),type TEXT,start_date TEXT,end_date TEXT,days INTEGER,comment TEXT,status TEXT,created_at TEXT,updated_at TEXT);
        CREATE TABLE IF NOT EXISTS request_history(id INTEGER PRIMARY KEY AUTOINCREMENT,request_id INTEGER REFERENCES requests(id),actor_id INTEGER REFERENCES users(id),action TEXT,comment TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER REFERENCES users(id),title TEXT,body TEXT,kind TEXT,target_id INTEGER,is_read INTEGER DEFAULT 0,created_at TEXT);
        CREATE TABLE IF NOT EXISTS courses(id INTEGER PRIMARY KEY,title TEXT,description TEXT,duration TEXT,lessons TEXT,quiz TEXT);
        CREATE TABLE IF NOT EXISTS enrollments(user_id INTEGER REFERENCES users(id),course_id INTEGER REFERENCES courses(id),assigned_by INTEGER REFERENCES users(id),completed_lessons TEXT DEFAULT '[]',score INTEGER,completed_at TEXT,assigned_at TEXT,PRIMARY KEY(user_id,course_id));
        CREATE TABLE IF NOT EXISTS knowledge(id INTEGER PRIMARY KEY,title TEXT,section TEXT,body TEXT,keywords TEXT,roles TEXT,updated_at TEXT);
        CREATE TABLE IF NOT EXISTS login_attempts(key TEXT PRIMARY KEY,count INTEGER,reset_at REAL);
        CREATE TABLE IF NOT EXISTS presence(user_id INTEGER PRIMARY KEY REFERENCES users(id),mode TEXT NOT NULL,location TEXT NOT NULL,from_location TEXT NOT NULL,changed_at REAL NOT NULL,arrive_at REAL NOT NULL,work_seconds REAL DEFAULT 0,break_seconds REAL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS work_shifts(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL REFERENCES users(id),started_at TEXT NOT NULL,ended_at TEXT,work_seconds REAL DEFAULT 0,break_seconds REAL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS direct_messages(id INTEGER PRIMARY KEY AUTOINCREMENT,sender_id INTEGER NOT NULL REFERENCES users(id),recipient_id INTEGER NOT NULL REFERENCES users(id),body TEXT NOT NULL,created_at TEXT NOT NULL,read_at TEXT);
        ''')
        c.execute('CREATE TABLE IF NOT EXISTS office_seats(user_id INTEGER PRIMARY KEY REFERENCES users(id),seat_key TEXT UNIQUE NOT NULL)')
        existing=c.execute('SELECT id,role FROM users').fetchall()
        for person in existing:
            key='manager' if person['role']=='manager' else 'hr' if person['role']=='hr' else 'seat4' if person['id']==1 else 'seat5'
            c.execute('INSERT OR IGNORE INTO office_seats VALUES(?,?)',(person['id'],key))
        if existing:
            migrate_demo_passwords(c)
            seed_branch_people(c)
            return
        people = [
            (2,'manager','Санжар Ким','manager','Руководитель филиала','Операционный отдел',None, '2022-04-18',24),
            (1,'employee','Алина Петрова Сергеевна','employee','Специалист по работе с клиентами','Операционный отдел',2,'2024-03-11',24),
            (3,'hr','Аружан Бекенова','hr','HR-специалист','HR',None,'2023-06-01',24),
            (4,'colleague','Тимур Садык','employee','Специалист склада','Склад',None,'2025-01-20',18)]
        for uid,login,name,role,pos,dept,manager,hired,leave in people:
            salt=secrets.token_hex(16)
            # Public demo credential; generated hash is persisted, plaintext is never stored.
            c.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(uid,login,name,role,'Jana Post · демо',pos,dept,manager,hired,leave,salt,password_hash(DEMO_PASSWORDS[login],salt)))
        for uid,key in [(1,'seat4'),(2,'manager'),(3,'hr'),(4,'seat5')]:
            c.execute('INSERT OR IGNORE INTO office_seats VALUES(?,?)',(uid,key))
        seed_branch_people(c)
        migrate_demo_passwords(c)
        lessons = [
            {'title':'Единое рабочее пространство','body':'JanaMen объединяет профиль, HR-заявки, обучение и помощь. Откройте нужную комнату на пиксельной карте или используйте меню. Начинать рабочий таймер для доступа к сервисам не требуется.'},
            {'title':'Заявка и согласование','body':'В HR-сервисах выберите даты отпуска и отправьте заявку. Статус и история доступны в «Моих заявках». Руководитель согласует заявки своей команды, HR может обработать заявку. Решение приходит в уведомлениях.'},
            {'title':'Данные и помощь','body':'Официальные кадровые поля доступны только для чтения. Исправления передаются HR. HR-ассистент использует подготовленную демонстрационную базу и показывает источник. Не отправляйте реальные персональные данные в демонстрационный прототип.'}]
        quiz = [
            {'question':'Где отслеживать отпуск?','options':['В моих заявках','В списке проектов','Только по телефону'],'correct':0},
            {'question':'Кто согласует заявку команды?','options':['Любой коллега','Руководитель команды или HR','Сам заявитель'],'correct':1},
            {'question':'Что делать, если в базе нет ответа?','options':['Придумать правило','Запросить чужие документы','Обратиться в HR'],'correct':2}]
        c.execute('INSERT INTO courses VALUES(?,?,?,?,?,?)',(1,'Первый день в Jana Post','Знакомство с HR-сервисами и безопасной работой с данными. Демонстрационный курс.','5 минут',json.dumps(lessons,ensure_ascii=False),json.dumps(quiz,ensure_ascii=False)))
        c.execute('INSERT INTO courses VALUES(?,?,?,?,?,?)',(2,'Безопасность персональных данных','Короткий практический курс для сотрудников. Демонстрационные материалы.','3 минуты',json.dumps([{'title':'Работа с данными','body':'Используйте только данные, доступные по вашей роли. Не передавайте пароли. При подозрительном запросе обратитесь в HR. В прототипе все аккаунты и кадровые записи вымышленные.'}],ensure_ascii=False),json.dumps([{'question':'Можно ли передать пароль коллеге?','options':['Да','Нет'],'correct':1}],ensure_ascii=False)))
        articles = [
            (1,'Демонстрационный порядок оформления отпуска','Подача и согласование','Откройте HR-сервисы → Отпуск, выберите даты и отправьте заявку. Она появится в «Моих заявках». Руководитель вашей команды или HR согласует либо отклонит её. В этом прототипе дни считаются календарными; проверяются доступный остаток и пересечения с активными заявками. Это правила демо, а не официальный регламент Jana Post.','отпуск,отпуска,отпускные,заявк,согласован,даты','employee,manager,hr'),
            (2,'Демонстрационная инструкция Jana Academy','Обучение','Назначенные курсы доступны в Jana Academy и профиле. Прочитайте все разделы и сдайте тест минимум на 67%. Результат и прогресс сохраняются. После завершения появится уведомление. HR назначает курсы в своём рабочем разделе.','курс,обучен,academy,академ,тест','employee,manager,hr'),
            (3,'Демонстрационная инструкция по кадровым данным','Исправление профиля','Компания, должность, подразделение, руководитель, дата приёма и остаток отпуска доступны только для чтения. Для исправления обратитесь в HR через раздел «Помощь». Будущий источник кадровых данных — 1С:ЗУП.','профил,данны,должност,прием,приём,исправ,компани','employee,manager,hr'),
            (4,'Демонстрационная инструкция по уведомлениям','События','В центре уведомлений отображаются изменения статусов заявок, назначение и завершение обучения. Нажмите на событие, чтобы открыть соответствующую карточку.','уведомлен,колокольчик,статус','employee,manager,hr'),
            (5,'Контакты HR в демо','Эскалация','Если надёжного ответа нет, обратитесь к HR-специалисту Аружан Бекеновой. В демонстрации используйте внутренний раздел «Помощь»; внешние сообщения не отправляются.','контакт,помощ,связ,эйчар,hr','employee,manager,hr'),
            (6,'Памятка согласующего в демо','Проверка заявки','Руководитель видит заявки непосредственной команды и может принять решение с комментарием. HR видит заявки компании. Никто не согласует собственную заявку. Чужие подразделения недоступны руководителю.','руководител,команд,согласующ,одобр,отклон','manager,hr')]
        for a in articles: c.execute('INSERT INTO knowledge VALUES(?,?,?,?,?,?,?)',(*a,now()))
        for uid in (1,2,3):
            c.execute('INSERT INTO enrollments(user_id,course_id,assigned_by,assigned_at) VALUES(?,?,?,?)',(uid,1,3,now()))
            notify(c,uid,'Назначен курс','Первый день в Jana Post','course',1)
        today=datetime.now(TZ).date()
        for uid,status,offset in [(1,'pending',10),(1,'approved',-35),(1,'rejected',-60),(4,'pending',15)]:
            start=today+timedelta(days=offset); end=start+timedelta(days=2)
            stamp=now()
            rid=c.execute('INSERT INTO requests(user_id,type,start_date,end_date,days,comment,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',(uid,'vacation',str(start),str(end),3,'Демонстрационная заявка',status,stamp,stamp)).lastrowid
            history(c,rid,uid,'Заявка создана')
            if status!='pending': history(c,rid,3,STATUS[status],'Пример завершённой заявки')
        notify(c,2,'Заявка ожидает решения','Алина отправила заявку на отпуск','request',1)


def init_db():
    init_db_base()
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS session_activity(token_hash TEXT PRIMARY KEY,seen_at REAL NOT NULL,joined INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS avatars(user_id INTEGER PRIMARY KEY REFERENCES users(id),appearance TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS employee_documents(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL REFERENCES users(id),title TEXT NOT NULL,category TEXT NOT NULL,filename TEXT NOT NULL,mime TEXT NOT NULL,size INTEGER NOT NULL,content BLOB NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS xp_awards(user_id INTEGER REFERENCES users(id),course_id INTEGER REFERENCES courses(id),xp INTEGER NOT NULL,badge TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(user_id,course_id));
        CREATE TABLE IF NOT EXISTS video_progress(user_id INTEGER REFERENCES users(id),course_id INTEGER REFERENCES courses(id),position REAL DEFAULT 0,watched REAL DEFAULT 0,updated REAL NOT NULL,PRIMARY KEY(user_id,course_id));
        """)
        migrate_leave(c)
        lessons_file=ROOT/'content'/'academy.json'
        if lessons_file.exists():
            for course in json.loads(lessons_file.read_text()):
                if 'video' not in course: continue
                cid=course['id']; seconds=course['duration_seconds']
                lesson={'title':course['title'],'body':'\n\n'.join(x['narration'] for x in course['scenes']),'video':course['video'],'poster':'/assets/'+course['slug']+'-poster.png','captions':'/assets/'+course['slug']+'.vtt','duration_seconds':seconds,'chapters':[{'title':x['title'],'start':x['start']} for x in course['scenes']],'badge':course['badge']}
                c.execute('INSERT OR IGNORE INTO courses VALUES(?,?,?,?,?,?)',(cid,course['title'],'Видеоурок на доске, 10 вопросов и значок за результат. Авторский демонстрационный материал.',f'{int(seconds)//60}:{int(seconds)%60:02d} · видео',json.dumps([lesson],ensure_ascii=False),json.dumps(course['quiz'],ensure_ascii=False)))
                for person in rows(c,'SELECT id FROM users'):
                    result=c.execute('INSERT OR IGNORE INTO enrollments(user_id,course_id,assigned_by,assigned_at) VALUES(?,?,?,?)',(person['id'],cid,3,now()))
                    if result.rowcount: notify(c,person['id'],'Назначен видеокурс',course['title'],'course',cid)

LEAVE_TYPES={'vacation':'Ежегодный оплачиваемый отпуск','unpaid':'Отпуск без сохранения зарплаты','study':'Учебный отпуск','social':'Социальный отпуск'}

def leave_route(c,owner):
    uid=owner['id']
    manager=owner['manager_id']
    if manager is None or manager==uid: manager=2 if uid==10 else 10
    hr=11 if uid==3 else 3
    require(len({uid,manager,hr})==3,409,'Для сотрудника не настроена независимая цепочка согласования')
    return [{'user_id':manager,'stage':'Руководитель','status':'waiting'},{'user_id':hr,'stage':'HR','status':'waiting'}]

def migrate_leave(c):
    for uid,login,name,role,pos,seat in [(10,'director','Ерлан Аскаров','manager','Директор компании','tech0'),(11,'hr2','Дана Сейтова','hr','HR-специалист · замещение','tech1')]:
        if not c.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone():
            salt=secrets.token_hex(16)
            c.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(uid,login,name,role,'Jana Post · демо',pos,'Управление' if role=='manager' else 'HR',None,'2023-01-10',24,salt,password_hash(DEMO_PASSWORDS[login],salt)))
        c.execute('INSERT OR IGNORE INTO office_seats VALUES(?,?)',(uid,seat))
    columns={r['name'] for r in c.execute('PRAGMA table_info(requests)')}
    if 'approval_route' not in columns:c.execute("ALTER TABLE requests ADD COLUMN approval_route TEXT NOT NULL DEFAULT '[]'")
    if 'stage_index' not in columns:c.execute('ALTER TABLE requests ADD COLUMN stage_index INTEGER NOT NULL DEFAULT 0')
    for r in rows(c,"SELECT * FROM requests WHERE status='pending' AND approval_route='[]'"):
        owner=c.execute('SELECT * FROM users WHERE id=?',(r['user_id'],)).fetchone()
        c.execute('UPDATE requests SET approval_route=? WHERE id=?',(json.dumps(leave_route(c,owner)),r['id']))
    if not c.execute("SELECT 1 FROM app_migrations WHERE name='leave_chain_v1'").fetchone():
        c.execute("UPDATE notifications SET is_read=1 WHERE kind='request' AND target_id IN (SELECT id FROM requests WHERE status='pending')")
        for r in rows(c,"SELECT * FROM requests WHERE status='pending'"):
            step=json.loads(r['approval_route'])[r['stage_index']]
            notify(c,step['user_id'],'Заявка ожидает вашего решения','Настроен последовательный маршрут согласования','request',r['id'])
        c.execute("INSERT INTO app_migrations VALUES('leave_chain_v1')")
    c.execute("UPDATE knowledge SET body=? WHERE id=1",('Демонстрационный порядок: выберите тип отпуска и даты. Сначала заявку рассматривает руководитель, затем HR. Только после двух согласований отпуск одобрен. При возврате исправьте заявку и отправьте заново. Для оплачиваемого ежегодного отпуска учитывается остаток; другие типы не уменьшают этот остаток. Это правила демонстрации, не кадровый регламент.',))

def leave_view(c,u,r):
    r=dict(r);route=json.loads(r.pop('approval_route','[]'))
    for step in route:
        p=c.execute('SELECT name FROM users WHERE id=?',(step['user_id'],)).fetchone()
        step['name']=p['name'] if p else 'Не назначен'
    r['route']=route
    current=route[r['stage_index']] if r['status']=='pending' and route else None
    r['current_approver']=current
    r['can_decide']=bool(current and current['user_id']==u['id'] and r['user_id']!=u['id'])
    r['can_edit']=r['user_id']==u['id'] and r['status'] in ('returned','rejected')
    r['type_label']=LEAVE_TYPES.get(r['type'],r['type'])
    r['stage_label']=('Ожидает: '+current['name']) if current else STATUS.get(r['status'],r['status'])
    return r

def validate_leave(c,u,b,exclude=0):
    kind=b.get('type','vacation');require(kind in LEAVE_TYPES,400,'Выберите тип отпуска')
    start=date.fromisoformat(b.get('start_date',''));end=date.fromisoformat(b.get('end_date',''))
    require(start>=datetime.now(TZ).date() and end>=start,400,'Выберите будущие даты, окончание не раньше начала')
    days=(end-start).days+1;require(days<=90,400,'Период в демонстрации — не больше 90 дней')
    comment=str(b.get('comment','')).strip();require(len(comment)<=1000,400,'Комментарий до 1000 символов')
    current=c.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone()
    if kind=='vacation':require(days<=public_user(c,current)['available_days'],400,'Недостаточно доступных дней ежегодного отпуска')
    require(not c.execute("SELECT 1 FROM requests WHERE user_id=? AND id!=? AND status IN ('pending','approved') AND start_date<=? AND end_date>=?",(u['id'],exclude,str(end),str(start))).fetchone(),409,'Даты пересекаются с действующей заявкой')
    return kind,str(start),str(end),days,comment


def learning_stats(c,uid):
    awards=rows(c,'SELECT a.xp,a.badge,a.created_at,c.title FROM xp_awards a JOIN courses c ON c.id=a.course_id WHERE a.user_id=? ORDER BY a.created_at',(uid,))
    xp=sum(a['xp'] for a in awards)
    return {'xp':xp,'level':1+xp//100,'next_level_xp':100-xp%100,'level_progress':xp%100,'badges':awards}

def can_read_documents(u,owner):
    return u['id']==owner['id'] or u['role']=='hr' or (u['role']=='manager' and owner['manager_id']==u['id'])

def directory_person(c,u,person):
    return {**{k:person[k] for k in ('id','name','position','department')},'helps_with':{'employee':'Рабочие вопросы своего подразделения','manager':'Организация работы команды и согласование заявок','hr':'Кадровые вопросы, документы и обучение'}[person['role']],'can_documents':can_read_documents(u,person),'is_self':u['id']==person['id']}

def avatar_data(c,uid):
    saved=c.execute('SELECT appearance FROM avatars WHERE user_id=?',(uid,)).fetchone()
    return json.loads(saved['appearance']) if saved else {'base':{1:0,2:1,3:2,4:9,5:3,6:4,7:5,8:6,9:7,10:8,11:10}.get(uid,3),'hair':'original','skin':'original','clothes':'original'}

class BinaryDownload:
    def __init__(self,data,mime,filename):self.data=data;self.mime=mime;self.filename=filename

class APIError(Exception):
    def __init__(self,status,message): self.status=status; self.message=message
def require(ok,status=403,message='Недостаточно прав'): 
    if not ok: raise APIError(status,message)
def presence_data(c,uid):
    stamp=time.time()
    seat=c.execute('SELECT seat_key FROM office_seats WHERE user_id=?',(uid,)).fetchone()
    seat_key=seat['seat_key'] if seat else 'seat4'
    p=c.execute('SELECT * FROM presence WHERE user_id=?',(uid,)).fetchone()
    if not p: return {'user_id':uid,'mode':'off','location':'entrance','from_location':'entrance','changed_at':stamp,'arrive_at':stamp,'work_seconds':0,'break_seconds':0,'server_time':stamp,'seat_key':seat_key}
    result=dict(p)
    elapsed=max(0,stamp-p['changed_at'])
    if p['mode']=='work': result['work_seconds']+=elapsed
    if p['mode']=='break': result['break_seconds']+=elapsed
    result['server_time']=stamp
    result['seat_key']=seat_key
    return result
def live_person(c,p):
    active=c.execute('SELECT 1 FROM sessions s JOIN session_activity a ON a.token_hash=s.token_hash WHERE s.user_id=? AND s.expires>? AND a.seen_at>? AND a.joined=1 LIMIT 1',(p['id'],time.time(),time.time()-90)).fetchone()
    presence=presence_data(c,p['id'])
    online=bool(active)
    if not online:
        presence.update(mode='off',location='entrance',from_location='entrance',changed_at=0,arrive_at=0)
    # Map viewers see location and status, never another employee's work totals.
    presence.pop('work_seconds',None);presence.pop('break_seconds',None)
    return {**p,'online':online,'presence':presence}

def public_user(c,u):
    result={k:u[k] for k in ('id','login','name','role','company','position','department','manager_id','hired_at','vacation_days')}
    m=c.execute('SELECT name FROM users WHERE id=?',(u['manager_id'],)).fetchone()
    result['manager_name']=m['name'] if m else 'Не назначен'
    reserved=c.execute("SELECT coalesce(sum(days),0) FROM requests WHERE user_id=? AND status='pending' AND type='vacation'",(u['id'],)).fetchone()[0]
    result['reserved_days']=reserved; result['available_days']=max(0,u['vacation_days']-reserved)
    result['learning']=learning_stats(c,u['id'])
    return result
def accessible_request(c,u,rid):
    r=c.execute('SELECT r.*,u.name as employee_name,u.department,u.manager_id FROM requests r JOIN users u ON u.id=r.user_id WHERE r.id=?',(rid,)).fetchone()
    require(r is not None,404,'Заявка не найдена')
    require(r['user_id']==u['id'] or any(step['user_id']==u['id'] for step in json.loads(r['approval_route'])) or u['role']=='hr' or (u['role']=='manager' and r['manager_id']==u['id']))
    return dict(r)
def course_data(c,uid):
    result=rows(c,'SELECT c.id,c.title,c.description,c.duration,e.completed_lessons,e.score,e.completed_at,e.assigned_at FROM courses c LEFT JOIN enrollments e ON e.course_id=c.id AND e.user_id=?',(uid,))
    for r in result:
        lessons=json.loads(c.execute('SELECT lessons FROM courses WHERE id=?',(r['id'],)).fetchone()[0])
        r['video']=any(l.get('video') for l in lessons)
        r['pass_score']=70 if r['video'] else 67
        r['assigned']=r['assigned_at'] is not None
        r['completed_lessons']=json.loads(r['completed_lessons'] or '[]')
        r['lesson_count']=len(lessons)
        r['progress']=100 if r['completed_at'] else round(len(r['completed_lessons'])/len(lessons)*80)
        if r['video'] and not r['completed_at']:
            watched=c.execute('SELECT watched FROM video_progress WHERE user_id=? AND course_id=?',(uid,r['id'])).fetchone()
            r['progress']=max(r['progress'],min(80,round((watched['watched'] if watched else 0)/lessons[0]['duration_seconds']*80)))
    return result

class Handler(BaseHTTPRequestHandler):
    server_version='JanaMen/1.0'
    def log_message(self,fmt,*args): pass
    def response(self,status,data=None):
        if isinstance(data,BinaryDownload):
            self.send_response(200);self.send_header('Content-Type',data.mime);self.send_header('Content-Length',str(len(data.data)));self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(data.filename));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data.data);return
        body=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        if getattr(self,'cookie_out',None): self.send_header('Set-Cookie',self.cookie_out)
        self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path.startswith('/api/'): self.handle_api('GET'); return
        routes={'/live.js':'live.js','/leave.js':'leave.js','/avatars.js':'avatars.js','/':'index.html','/app.js':'app.js','/app.css':'app.css','/office.js':'office.js','/learning.js':'learning.js'}
        url_path=self.path.split('?')[0]
        filename=routes.get(url_path)
        if url_path.startswith('/assets/') and re.fullmatch(r'/assets/[A-Za-z0-9_.-]+',url_path):
            candidate=ROOT/'static'/url_path.lstrip('/')
            if candidate.is_file(): filename=url_path.lstrip('/')
        if not filename: self.send_error(404); return
        if filename.endswith('.mp4'):
            self.serve_video(ROOT/'static'/filename);return
        data=(ROOT/'static'/filename).read_bytes()
        self.send_response(200); self.send_header('Content-Type',{'html':'text/html; charset=utf-8','js':'application/javascript; charset=utf-8','css':'text/css; charset=utf-8','png':'image/png','vtt':'text/vtt; charset=utf-8','ttf':'font/ttf','txt':'text/plain; charset=utf-8'}.get(filename.split('.')[-1],'application/octet-stream'))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
    def serve_video(self,path):
        size=path.stat().st_size;start=0;end=size-1;status=200
        value=self.headers.get('Range')
        if value:
            match=re.fullmatch(r'bytes=(\d+)-(\d*)',value)
            if not match or int(match[1])>=size:
                self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.send_header('Content-Length','0');self.end_headers();return
            start=int(match[1]);end=min(int(match[2]) if match[2] else size-1,size-1)
            if end<start:self.send_error(416);return
            status=206
        self.send_response(status);self.send_header('Content-Type','video/mp4');self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(end-start+1));self.send_header('Cache-Control','no-cache')
        if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.end_headers()
        try:
            with path.open('rb') as f:
                f.seek(start);remaining=end-start+1
                while remaining:
                    block=f.read(min(65536,remaining))
                    if not block:break
                    self.wfile.write(block);remaining-=len(block)
        except (BrokenPipeError,ConnectionResetError):pass
    def do_POST(self): self.handle_api('POST')
    def do_PATCH(self): self.handle_api('PATCH')
    def handle_api(self,method):
        self.cookie_out=None
        try:
            require(self.path.startswith('/api/'),404,'Не найдено')
            length=int(self.headers.get('Content-Length','0'))
            require(0<=length<=(12_000_000 if self.path=='/api/documents' and method=='POST' else 20000),413,'Слишком большой запрос')
            try: body=json.loads(self.rfile.read(length)) if length else {}
            except (ValueError,UnicodeError): raise APIError(400,'Некорректный JSON')
            require(isinstance(body,dict),400,'Ожидается JSON-объект')
            with connect() as c:
                result=self.route(c,method,self.path.split('?')[0],body)
            self.response(200,result)
        except APIError as e: self.response(e.status,{'error':e.message})
        except (ValueError,TypeError,KeyError): self.response(400,{'error':'Проверьте формат данных'})
        except sqlite3.IntegrityError: self.response(409,{'error':'Данные уже существуют или конфликтуют'})
        except Exception:
            import traceback; traceback.print_exc()
            self.response(500,{'error':'Ошибка сервера'})
    def route(self,c,method,path,b):
        if path=='/api/login' and method=='POST':
            key=self.client_address[0]; t=time.time()
            attempt=c.execute('SELECT * FROM login_attempts WHERE key=?',(key,)).fetchone()
            require(not attempt or attempt['reset_at']<t or attempt['count']<20,429,'Слишком много попыток. Повторите через минуту.')
            u=c.execute('SELECT * FROM users WHERE login=?',(str(b.get('login',''))[:80],)).fetchone()
            valid=u and hmac.compare_digest(password_hash(str(b.get('password','')),u['salt']),u['password_hash'])
            if not valid:
                count=attempt['count']+1 if attempt and attempt['reset_at']>t else 1
                c.execute('INSERT OR REPLACE INTO login_attempts VALUES(?,?,?)',(key,count,t+60)); c.commit()
                raise APIError(401,'Неверный логин или пароль')
            c.execute('DELETE FROM login_attempts WHERE key=?',(key,))
            token=secrets.token_urlsafe(32); csrf=secrets.token_urlsafe(24)
            c.execute('DELETE FROM sessions WHERE expires<?',(t,))
            c.execute('DELETE FROM session_activity WHERE token_hash NOT IN (SELECT token_hash FROM sessions)')
            c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),u['id'],csrf,t+43200))
            c.execute('INSERT INTO session_activity VALUES(?,?,0)',(hashlib.sha256(token.encode()).hexdigest(),t))
            if not b.get('tab_scoped'): self.cookie_out='janamen_session='+token+'; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200'
            return {'user':public_user(c,u),'csrf':csrf,**({'token':token} if b.get('tab_scoped') else {})}
        cookie=SimpleCookie()
        try: cookie.load(self.headers.get('Cookie',''))
        except Exception: raise APIError(401,'Войдите в аккаунт')
        auth=self.headers.get('Authorization')
        token=(auth[7:] if auth.startswith('Bearer ') else '') if auth is not None else (cookie['janamen_session'].value if 'janamen_session' in cookie else '')
        session=c.execute('SELECT * FROM sessions WHERE token_hash=? AND expires>?',(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
        require(session is not None,401,'Войдите в аккаунт')
        u=c.execute('SELECT * FROM users WHERE id=?',(session['user_id'],)).fetchone()
        if method!='GET': require(hmac.compare_digest(self.headers.get('X-CSRF-Token',''),session['csrf']),403,'Недействительный защитный токен')
        if path=='/api/heartbeat' and method=='POST':
            c.execute('INSERT INTO session_activity VALUES(?,?,0) ON CONFLICT(token_hash) DO UPDATE SET seen_at=excluded.seen_at',(session['token_hash'],time.time()))
            return {'ok':True}
        if path=='/api/disconnect' and method=='POST':
            c.execute('UPDATE session_activity SET seen_at=0 WHERE token_hash=?',(session['token_hash'],))
            return {'ok':True}
        if path=='/api/office-live' and method=='GET':
            return [live_person(c,p) for p in rows(c,'SELECT id,name,position FROM users')]
        if path=='/api/me' and method=='GET': return {'user':public_user(c,u),'csrf':session['csrf']}
        if path=='/api/avatars' and method=='GET':
            return {str(p['id']):avatar_data(c,p['id']) for p in rows(c,'SELECT id FROM users')}
        if path=='/api/avatar' and method=='POST':
            require(set(b)=={'base','hair','skin','clothes'},400,'Укажите только настройки своего аватара')
            require(type(b['base']) is int and 0<=b['base']<15,400,'Выберите персонажа')
            for key in ('hair','skin','clothes'):
                require(isinstance(b[key],str) and (b[key]=='original' or re.fullmatch(r'#[0-9a-fA-F]{6}',b[key])),400,'Некорректный цвет')
            c.execute('INSERT OR REPLACE INTO avatars VALUES(?,?)',(u['id'],json.dumps(b)))
            return avatar_data(c,u['id'])
        if path=='/api/directory' and method=='GET':
            return [directory_person(c,u,p) for p in rows(c,'SELECT * FROM users ORDER BY name')]
        match=re.fullmatch(r'/api/people/(\d+)(/documents)?',path)
        if match and method=='GET':
            owner=c.execute('SELECT * FROM users WHERE id=?',(int(match[1]),)).fetchone();require(owner is not None,404,'Сотрудник не найден')
            if not match[2]: return directory_person(c,u,owner)
            require(can_read_documents(u,owner))
            return rows(c,'SELECT id,user_id,title,category,filename,size,created_at FROM employee_documents WHERE user_id=? ORDER BY id DESC',(owner['id'],))
        if path=='/api/documents' and method=='POST':
            title=str(b.get('title','')).strip();category=str(b.get('category','')).strip();filename=str(b.get('filename',''))
            require(1<=len(title)<=120 and category in ('Сертификат','Рабочий материал','Портфолио','Другое'),400,'Укажите название и категорию')
            require(1<=len(filename)<=180 and '/' not in filename and '\\' not in filename and not any(ord(x)<32 for x in filename),400,'Некорректное имя файла')
            try: data=base64.b64decode(b.get('content',''),validate=True)
            except (ValueError,binascii.Error): raise APIError(400,'Файл повреждён')
            require(0<len(data)<=8*1024*1024,413,'Файл должен быть не больше 8 МБ')
            ext=Path(filename).suffix.lower();mime={'.pdf':'application/pdf','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}.get(ext)
            require(mime is not None,400,'Поддерживаются PDF, DOCX, PNG и JPG')
            valid=(ext=='.pdf' and data.startswith(b'%PDF-')) or (ext=='.png' and data.startswith(b'\x89PNG\r\n\x1a\n')) or (ext in ('.jpg','.jpeg') and data.startswith(b'\xff\xd8\xff'))
            if ext=='.docx':
                try:
                    with zipfile.ZipFile(io.BytesIO(data)) as z:
                        names=z.namelist();valid='word/document.xml' in names and '[Content_Types].xml' in names and not any('vbaProject' in n for n in names) and sum(i.file_size for i in z.infolist())<=40*1024*1024
                except (zipfile.BadZipFile,ValueError): valid=False
            require(valid,400,'Содержимое файла не соответствует формату')
            c.execute('BEGIN IMMEDIATE')
            total=c.execute('SELECT count(*),coalesce(sum(size),0) FROM employee_documents WHERE user_id=?',(u['id'],)).fetchone()
            require(total[0]<100 and total[1]+len(data)<=50*1024*1024,413,'Лимит документов: 100 файлов или 50 МБ')
            did=c.execute('INSERT INTO employee_documents(user_id,title,category,filename,mime,size,content,created_at) VALUES(?,?,?,?,?,?,?,?)',(u['id'],title,category,filename,mime,len(data),data,now())).lastrowid
            return {'id':did,'title':title,'url':'/api/documents/'+str(did)+'/download'}
        match=re.fullmatch(r'/api/documents/(\d+)/(download|delete)',path)
        if match:
            doc=c.execute('SELECT * FROM employee_documents WHERE id=?',(int(match[1]),)).fetchone();require(doc is not None,404,'Документ не найден')
            owner=c.execute('SELECT * FROM users WHERE id=?',(doc['user_id'],)).fetchone()
            if match[2]=='download' and method=='GET':
                require(can_read_documents(u,owner));return BinaryDownload(doc['content'],doc['mime'],doc['filename'])
            if match[2]=='delete' and method=='POST':
                require(doc['user_id']==u['id']);c.execute('DELETE FROM employee_documents WHERE id=?',(doc['id'],));return {'ok':True}
        match=re.fullmatch(r'/api/courses/(\d+)/video-progress',path)
        if match and method=='POST':
            cid=int(match[1]);course=c.execute('SELECT * FROM courses WHERE id=?',(cid,)).fetchone();require(course is not None,404,'Курс не найден')
            lessons=json.loads(course['lessons']);require(lessons[0].get('video'),400,'В курсе нет видео')
            require(c.execute('SELECT 1 FROM enrollments WHERE user_id=? AND course_id=?',(u['id'],cid)).fetchone(),403,'Курс не назначен')
            position=float(b.get('position',0));duration=lessons[0]['duration_seconds'];require(0<=position<=duration+1,400,'Некорректная позиция')
            c.execute('BEGIN IMMEDIATE');stamp=time.time();old=c.execute('SELECT * FROM video_progress WHERE user_id=? AND course_id=?',(u['id'],cid)).fetchone()
            watched=old['watched'] if old else 0
            if old and old['position']<=watched+2 and 0<=position-old['position']<=min(20,(stamp-old['updated'])*2.25+1): watched=max(watched,position)
            c.execute('INSERT OR REPLACE INTO video_progress VALUES(?,?,?,?,?)',(u['id'],cid,position,watched,stamp))
            return {'watched':watched,'duration':duration,'ready':watched>=duration*.9}
        if path=='/api/presence' and method=='GET':
            return presence_data(c,u['id'])
        if path=='/api/presence' and method=='POST':
            locations={'work':'desk','off':'entrance','break':None}
            mode=b.get('mode'); location=b.get('location')
            require(mode in locations,400,'Неизвестный статус')
            if mode=='break': require(location in ('kitchen','buffet','lounge'),400,'Выберите место перерыва')
            else: location=locations[mode]
            c.execute('BEGIN IMMEDIATE')
            c.execute('INSERT INTO session_activity VALUES(?,?,1) ON CONFLICT(token_hash) DO UPDATE SET seen_at=excluded.seen_at,joined=1',(session['token_hash'],time.time()))
            old=presence_data(c,u['id']); stamp=time.time()
            entering=b.get('enter') is True and mode=='work'
            require(entering or stamp>=old['arrive_at'],409,'Сначала дождитесь, пока персонаж дойдёт')
            require(mode!='break' or old['mode']!='off',400,'Сначала начните рабочий день')
            if not entering and old['mode']==mode and old['location']==location: return old
            work_seconds=0 if entering else old['work_seconds']
            break_seconds=0 if entering else old['break_seconds']
            if entering:
                c.execute('UPDATE work_shifts SET ended_at=?,work_seconds=?,break_seconds=? WHERE user_id=? AND ended_at IS NULL',
                          (now(),old['work_seconds'],old['break_seconds'],u['id']))
                c.execute('INSERT INTO work_shifts(user_id,started_at) VALUES(?,?)',(u['id'],now()))
            completed=None
            if mode=='off':
                active=c.execute('SELECT id,started_at FROM work_shifts WHERE user_id=? AND ended_at IS NULL ORDER BY id DESC LIMIT 1',(u['id'],)).fetchone()
                if active:
                    ended=now()
                    c.execute('UPDATE work_shifts SET ended_at=?,work_seconds=?,break_seconds=? WHERE id=?',
                              (ended,old['work_seconds'],old['break_seconds'],active['id']))
                    completed={'id':active['id'],'started_at':active['started_at'],'ended_at':ended,
                               'work_seconds':round(old['work_seconds']),'break_seconds':round(old['break_seconds'])}
                    recipients=[]
                    if u['manager_id']: recipients.append(u['manager_id'])
                    recipients += [x['id'] for x in rows(c,"SELECT id FROM users WHERE role='hr'") if x['id']!=u['id']]
                    for rid in set(recipients):
                        notify(c,rid,'Смена завершена',f'{u["name"]} · отработано {round(old["work_seconds"]//3600):02}:{round(old["work_seconds"]%3600//60):02}','shift',active['id'])
            c.execute('INSERT OR REPLACE INTO presence VALUES(?,?,?,?,?,?,?,?)',(u['id'],mode,location,'entrance' if entering else old['location'],stamp,stamp+(7.5 if entering or mode=='off' else 4.8),work_seconds,break_seconds))
            result=presence_data(c,u['id'])
            result['completed_shift']=completed
            return result
        if path=='/api/shifts' and method=='GET':
            return rows(c,'SELECT * FROM work_shifts WHERE user_id=? ORDER BY id DESC LIMIT 60',(u['id'],))
        match=re.fullmatch(r'/api/people/(\d+)/shifts',path)
        if match and method=='GET':
            owner=c.execute('SELECT * FROM users WHERE id=?',(int(match[1]),)).fetchone();require(owner is not None,404,'Сотрудник не найден')
            require(u['id']==owner['id'] or u['role']=='hr' or (u['role']=='manager' and owner['manager_id']==u['id']))
            return rows(c,'SELECT * FROM work_shifts WHERE user_id=? ORDER BY id DESC LIMIT 60',(owner['id'],))
        if path=='/api/messages/contacts' and method=='GET':
            people=rows(c,'SELECT id,name,position,department FROM users WHERE id!=? ORDER BY name',(u['id'],))
            for person in people:
                last=c.execute('SELECT body,created_at FROM direct_messages WHERE (sender_id=? AND recipient_id=?) OR (sender_id=? AND recipient_id=?) ORDER BY id DESC LIMIT 1',(u['id'],person['id'],person['id'],u['id'])).fetchone()
                person['last_message']=dict(last) if last else None
                person['unread']=c.execute('SELECT count(*) FROM direct_messages WHERE sender_id=? AND recipient_id=? AND read_at IS NULL',(person['id'],u['id'])).fetchone()[0]
            return people
        match=re.fullmatch(r'/api/messages/(\d+)',path)
        if match and method=='GET':
            peer=int(match[1]);require(peer!=u['id'] and c.execute('SELECT 1 FROM users WHERE id=?',(peer,)).fetchone(),404,'Сотрудник не найден')
            c.execute('UPDATE direct_messages SET read_at=? WHERE sender_id=? AND recipient_id=? AND read_at IS NULL',(now(),peer,u['id']))
            return rows(c,'SELECT m.*,s.name sender_name,r.name recipient_name FROM direct_messages m JOIN users s ON s.id=m.sender_id JOIN users r ON r.id=m.recipient_id WHERE (sender_id=? AND recipient_id=?) OR (sender_id=? AND recipient_id=?) ORDER BY id LIMIT 300',(u['id'],peer,peer,u['id']))
        if path=='/api/messages' and method=='POST':
            peer=int(b.get('recipient_id',0));body=str(b.get('body','')).strip()
            require(peer!=u['id'] and c.execute('SELECT 1 FROM users WHERE id=?',(peer,)).fetchone(),404,'Сотрудник не найден')
            require(1<=len(body)<=2000,400,'Сообщение должно содержать от 1 до 2000 символов')
            mid=c.execute('INSERT INTO direct_messages(sender_id,recipient_id,body,created_at) VALUES(?,?,?,?)',(u['id'],peer,body,now())).lastrowid
            notify(c,peer,'Новое сообщение',f'{u["name"]}: {body[:120]}','message',u['id'])
            return {'id':mid,'ok':True}
        if path=='/api/office-team' and method=='GET':
            require(u['role'] in ('manager','hr'))
            members=rows(c,'SELECT id,name,position,department FROM users'+(' WHERE manager_id=?' if u['role']=='manager' else ' WHERE id!=?'),(u['id'],))
            return [{**p,'presence':presence_data(c,p['id'])} for p in members]
        if path=='/api/logout' and method=='POST':
            c.execute('DELETE FROM session_activity WHERE token_hash=?',(session['token_hash'],))
            c.execute('DELETE FROM sessions WHERE token_hash=?',(session['token_hash'],)); self.cookie_out='janamen_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'
            return {'ok':True}
        if path=='/api/leave-options' and method=='GET':
            route=leave_route(c,u)
            for step in route:step['name']=c.execute('SELECT name FROM users WHERE id=?',(step['user_id'],)).fetchone()['name']
            return {'types':LEAVE_TYPES,'route':route}
        if path=='/api/requests' and method=='GET':
            result=rows(c,'SELECT r.*,p.name as employee_name,p.department,p.manager_id FROM requests r JOIN users p ON p.id=r.user_id ORDER BY r.id DESC')
            return [leave_view(c,u,r) for r in result if r['user_id']==u['id'] or any(step['user_id']==u['id'] for step in json.loads(r['approval_route'])) or u['role']=='hr' or (u['role']=='manager' and r['manager_id']==u['id'])]
        if path=='/api/requests' and method=='POST':
            c.execute('BEGIN IMMEDIATE')
            kind,start,end,days,comment=validate_leave(c,u,b)
            route=leave_route(c,u);stamp=now()
            rid=c.execute('INSERT INTO requests(user_id,type,start_date,end_date,days,comment,status,created_at,updated_at,approval_route,stage_index) VALUES(?,?,?,?,?,?,?,?,?,?,0)',(u['id'],kind,start,end,days,comment,'pending',stamp,stamp,json.dumps(route))).lastrowid
            history(c,rid,u['id'],'Заявка создана',f'{LEAVE_TYPES[kind]} · {start} — {end}. {comment}')
            notify(c,u['id'],'Заявка отправлена','Первый этап: руководитель','request',rid)
            notify(c,route[0]['user_id'],'Новая заявка на согласование',u['name']+' · '+LEAVE_TYPES[kind],'request',rid)
            return {'id':rid}
        match=re.fullmatch(r'/api/requests/(\d+)(/resubmit)?',path)
        if match and method=='GET' and not match[2]:
            r=leave_view(c,u,accessible_request(c,u,int(match[1])))
            r['history']=rows(c,'SELECT h.action,h.comment,h.created_at,p.name as actor_name FROM request_history h JOIN users p ON p.id=h.actor_id WHERE request_id=? ORDER BY h.id',(r['id'],))
            return r
        if match and method=='POST' and match[2]:
            c.execute('BEGIN IMMEDIATE');rid=int(match[1]);r=accessible_request(c,u,rid)
            require(r['user_id']==u['id']);require(r['status'] in ('returned','rejected'),409,'Редактирование доступно после возврата или отклонения')
            kind,start,end,days,comment=validate_leave(c,u,b,rid);route=leave_route(c,u)
            c.execute("UPDATE requests SET type=?,start_date=?,end_date=?,days=?,comment=?,status='pending',stage_index=0,approval_route=?,updated_at=? WHERE id=?",(kind,start,end,days,comment,json.dumps(route),now(),rid))
            history(c,rid,u['id'],'Исправлена и отправлена повторно',f'{LEAVE_TYPES[kind]} · {start} — {end}. {comment}')
            notify(c,route[0]['user_id'],'Заявка поступила повторно',u['name'],'request',rid)
            notify(c,u['id'],'Заявка отправлена повторно','Согласование начинается с руководителя','request',rid)
            return {'id':rid}
        match=re.fullmatch(r'/api/requests/(\d+)/decision',path)
        if match and method=='POST':
            c.execute('BEGIN IMMEDIATE');rid=int(match[1]);r=accessible_request(c,u,rid)
            require(r['user_id']!=u['id']);require(r['status']=='pending',409,'Решение уже принято')
            route=json.loads(r['approval_route']);index=r['stage_index'];step=route[index]
            require(step['user_id']==u['id'],403,'Сейчас решение принимает другой согласующий')
            status=b.get('status');require(status in ('approved','rejected','returned'),400,'Некорректное решение')
            comment=str(b.get('comment','')).strip();require(len(comment)<=1000,400,'Комментарий до 1000 символов')
            require(status=='approved' or len(comment)>=3,400,'Укажите причину отклонения или доработки')
            step.update(status=status,decided_at=now(),comment=comment)
            final=status=='approved' and index==len(route)-1
            history(c,rid,u['id'],step['stage']+': '+STATUS[status],comment)
            if status=='approved' and not final:
                index+=1;new_status='pending'
                notify(c,route[index]['user_id'],'Заявка ожидает решения HR',r['employee_name']+' · руководитель согласовал','request',rid)
                notify(c,r['user_id'],'Руководитель согласовал заявку','Ожидается решение HR. Отпуск ещё не согласован окончательно.','request',rid)
            else:
                new_status=status
                if final and r['type']=='vacation':
                    owner=c.execute('SELECT vacation_days FROM users WHERE id=?',(r['user_id'],)).fetchone()
                    require(owner['vacation_days']>=r['days'],409,'Недостаточно дней ежегодного отпуска')
                    c.execute('UPDATE users SET vacation_days=vacation_days-? WHERE id=?',(r['days'],r['user_id']))
                notify(c,r['user_id'],'Ваш отпуск согласован' if final else 'Заявка '+STATUS[status].lower(),comment or 'Все этапы согласования пройдены','request',rid)
            c.execute('UPDATE requests SET status=?,stage_index=?,approval_route=?,updated_at=? WHERE id=?',(new_status,index,json.dumps(route),now(),rid))
            return {'ok':True,'status':new_status,'final':final}
        if path=='/api/notifications' and method=='GET': return rows(c,'SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 100',(u['id'],))
        if path=='/api/notifications/read' and method=='POST':
            if b.get('id') is not None:
                result=c.execute('UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?',(int(b['id']),u['id'])); require(result.rowcount>0,404,'Уведомление не найдено')
            else: c.execute('UPDATE notifications SET is_read=1 WHERE user_id=?',(u['id'],))
            return {'ok':True}
        if path=='/api/courses' and method=='GET': return course_data(c,u['id'])
        match=re.fullmatch(r'/api/courses/(\d+)',path)
        if match and method=='GET':
            cid=int(match[1]); course=c.execute('SELECT * FROM courses WHERE id=?',(cid,)).fetchone(); require(course is not None,404,'Курс не найден')
            result=next(x for x in course_data(c,u['id']) if x['id']==cid)
            result['lessons']=json.loads(course['lessons'])
            progress=c.execute('SELECT watched FROM video_progress WHERE user_id=? AND course_id=?',(u['id'],cid)).fetchone()
            result['watched']=progress['watched'] if progress else 0
            result['quiz']=[{k:v for k,v in q.items() if k!='correct'} for q in json.loads(course['quiz'])]
            return result
        if path=='/api/enroll' and method=='POST':
            cid=int(b['course_id']); require(c.execute('SELECT id FROM courses WHERE id=?',(cid,)).fetchone() is not None,404,'Курс не найден')
            uid=int(b.get('user_id',u['id'])); require(uid==u['id'] or u['role']=='hr')
            require(c.execute('SELECT id FROM users WHERE id=?',(uid,)).fetchone() is not None,404,'Сотрудник не найден')
            existing=c.execute('SELECT 1 FROM enrollments WHERE user_id=? AND course_id=?',(uid,cid)).fetchone(); require(not existing,409,'Курс уже назначен')
            c.execute('INSERT INTO enrollments(user_id,course_id,assigned_by,assigned_at) VALUES(?,?,?,?)',(uid,cid,u['id'],now()))
            title=c.execute('SELECT title FROM courses WHERE id=?',(cid,)).fetchone()[0]
            notify(c,uid,'Назначен курс',title,'course',cid); return {'ok':True}
        match=re.fullmatch(r'/api/courses/(\d+)/(lesson|quiz)',path)
        if match and method=='POST':
            cid=int(match[1]); c.execute('BEGIN IMMEDIATE')
            course=c.execute('SELECT * FROM courses WHERE id=?',(cid,)).fetchone(); require(course is not None,404,'Курс не найден')
            enrollment=c.execute('SELECT * FROM enrollments WHERE user_id=? AND course_id=?',(u['id'],cid)).fetchone(); require(enrollment is not None,400,'Сначала запишитесь на курс')
            require(not enrollment['completed_at'],409,'Курс уже завершён')
            lessons=json.loads(course['lessons']); done=json.loads(enrollment['completed_lessons'])
            if match[2]=='lesson':
                idx=int(b['index']); require(0<=idx<len(lessons),400,'Раздел не найден')
                require(idx==0 or idx-1 in done,400,'Сначала пройдите предыдущий раздел')
                if lessons[idx].get('video'):
                    progress=c.execute('SELECT watched FROM video_progress WHERE user_id=? AND course_id=?',(u['id'],cid)).fetchone()
                    require(progress and progress['watched']>=lessons[idx]['duration_seconds']*.9,400,'Посмотрите не менее 90% видео, чтобы открыть тест')
                if idx not in done: done.append(idx)
                c.execute('UPDATE enrollments SET completed_lessons=? WHERE user_id=? AND course_id=?',(json.dumps(done),u['id'],cid)); return {'ok':True}
            require(len(done)==len(lessons),400,'Сначала прочитайте все разделы')
            quiz=json.loads(course['quiz']); answers=b.get('answers',[])
            require(isinstance(answers,list) and len(answers)==len(quiz) and all(type(a) is int and 0<=a<len(q['options']) for a,q in zip(answers,quiz)),400,'Ответьте на все вопросы')
            score=round(sum(a==q['correct'] for a,q in zip(answers,quiz))/len(quiz)*100); passed=score>=(70 if lessons[0].get('video') else 67)
            c.execute('UPDATE enrollments SET score=?,completed_at=? WHERE user_id=? AND course_id=?',(score,now() if passed else None,u['id'],cid))
            if passed:
                xp=100+max(0,score-70)
                c.execute('INSERT OR IGNORE INTO xp_awards VALUES(?,?,?,?,?)',(u['id'],cid,xp,lessons[0].get('badge',course['title']),now()))
                notify(c,u['id'],'Обучение завершено',f'{course["title"]} · результат {score}%','course',cid)
                for hr in rows(c,"SELECT id FROM users WHERE role='hr'"):
                    if hr['id']!=u['id']: notify(c,hr['id'],'Сотрудник завершил обучение',f'{u["name"]} · {course["title"]} · {score}%','team',u['id'])
            return {'score':score,'passed':passed,'xp_earned':xp if passed else 0,'learning':learning_stats(c,u['id'])}
        if path=='/api/team' and method=='GET':
            require(u['role'] in ('manager','hr'))
            people=rows(c,'SELECT * FROM users'+(' WHERE manager_id=?' if u['role']=='manager' else ''),(u['id'],) if u['role']=='manager' else ())
            result=[]
            for person in people:
                item=public_user(c,person); item['courses']=[x for x in course_data(c,person['id']) if x['assigned']]; result.append(item)
            return result
        if path=='/api/knowledge' and method=='GET': return [x for x in rows(c,'SELECT id,title,section,roles FROM knowledge') if u['role'] in x['roles'].split(',')]
        match=re.fullmatch(r'/api/knowledge/(\d+)',path)
        if match and method=='GET':
            article=c.execute('SELECT * FROM knowledge WHERE id=?',(int(match[1]),)).fetchone(); require(article is not None,404,'Источник не найден'); require(u['role'] in article['roles'].split(',')); return dict(article)
        if path=='/api/assistant/action' and method=='POST':
            require(b.get('action')=='send_message',400,'Неизвестное действие')
            peer=int(b.get('recipient_id',0));body=str(b.get('body','')).strip()
            require(peer!=u['id'] and c.execute('SELECT 1 FROM users WHERE id=?',(peer,)).fetchone(),404,'Получатель не найден')
            require(1<=len(body)<=2000,400,'Проверьте текст сообщения')
            c.execute('INSERT INTO direct_messages(sender_id,recipient_id,body,created_at) VALUES(?,?,?,?)',(u['id'],peer,body,now()))
            peer_name=c.execute('SELECT name FROM users WHERE id=?',(peer,)).fetchone()['name']
            notify(c,peer,'Новое сообщение',f'{u["name"]}: {body[:120]}','message',u['id'])
            return {'answer':f'Готово — сообщение отправлено сотруднику {peer_name}.','sources':[],'kind':'action_done','open':'messages'}
        if path=='/api/assistant' and method=='POST':
            original=str(b.get('question','')).strip();q=original.lower()
            require(2<=len(q)<=1500,400,'Вопрос от 2 до 1500 символов')
            base={'sources':[],'kind':'assistant'}
            privacy_terms=('покажи пароль','чужой пароль','паспорт другого','иин другого','зарплат','секретный токен')
            if any(w in q for w in privacy_terms):
                return {**base,'answer':'Я не раскрываю чужие персональные данные, пароли и секреты. Могу открыть рабочую карточку коллеги или помочь написать ему сообщение.','kind':'restricted'}
            if re.search(r'\b(привет|здравствуй|добрый день|сәлем)\b',q):
                return {**base,'answer':f'Здравствуйте, {u["name"].split()[0]}! Я помогу с отпуском, заявками, обучением, документами, рабочим временем и сообщениями коллегам. Напишите вопрос обычными словами.'}
            # Prepare a real internal-message action and ask for confirmation in the UI.
            if any(x in q for x in ('напиши','отправь сообщение','сообщи')):
                people=rows(c,'SELECT id,name FROM users WHERE id!=?',(u['id'],))
                target=None
                for person in people:
                    parts=[x.lower() for x in person['name'].split()]
                    if any(part in q for part in parts): target=person;break
                if target:
                    body=original.split(':',1)[1].strip() if ':' in original else original
                    for marker in ('что ','текст:','сообщение:'):
                        if marker in q:
                            body=original[q.index(marker)+len(marker):].strip(' :—-');break
                    if body==original:
                        body=re.sub(r'(?i)^(напиши|отправь сообщение|сообщи)\s+\S+(?:\s+\S+)?\s*[:,—-]?\s*','',original).strip()
                    require(bool(body),400,'Добавьте текст сообщения')
                    return {**base,'answer':f'Подготовила сообщение для {target["name"]}: «{body}». Отправить?',
                            'kind':'confirm_action','action':{'type':'send_message','recipient_id':target['id'],'recipient_name':target['name'],'body':body}}
                return {**base,'answer':'Не удалось определить получателя. Напишите имя, например: «Напиши Санжару: я закончила отчёт».','kind':'clarify'}
            me=public_user(c,u)
            if 'отпуск' in q:
                if any(x in q for x in ('сколько','остат','доступ')):
                    return {**base,'answer':f'У вас {me["vacation_days"]} дней отпуска, {me["reserved_days"]} зарезервировано заявками и {me["available_days"]} доступно для новой заявки.','sources':[{'id':'profile','title':'Мой профиль · текущие данные'}],'open':'services'}
                return {**base,'answer':'Оформить отпуск можно в HR-сервисах: выберите даты, добавьте комментарий и отправьте заявку. Статус и история появятся в «Моих заявках».','sources':[{'id':1,'title':'Порядок оформления отпуска'}],'open':'services'}
            if any(x in q for x in ('заявк','согласован','статус')):
                requests=rows(c,'SELECT type,status,start_date,end_date FROM requests WHERE user_id=? ORDER BY id DESC LIMIT 5',(u['id'],))
                text='; '.join(f'{r["start_date"]}–{r["end_date"]}: {STATUS.get(r["status"],r["status"])}' for r in requests) or 'У вас пока нет заявок.'
                return {**base,'answer':'Ваши последние заявки: '+text,'open':'requests'}
            if any(x in q for x in ('курс','обуч','academy','тест','xp','уров')):
                assigned=[x for x in course_data(c,u['id']) if x['assigned']]
                active=[x for x in assigned if not x['completed_at']]
                stats=learning_stats(c,u['id'])
                return {**base,'answer':f'Ваш уровень — {stats["level"]}, накоплено {stats["xp"]} XP. Активных курсов: {len(active)}. После просмотра видеокурса пройдите тест: минимум 7 из 10.','open':'academy'}
            if any(x in q for x in ('документ','файл','сертификат','портфолио')):
                count=c.execute('SELECT count(*) FROM employee_documents WHERE user_id=?',(u['id'],)).fetchone()[0]
                return {**base,'answer':f'В разделе «Мои документы» у вас {count} файлов. Можно загрузить PDF, DOCX, PNG или JPG до 8 МБ. Файлы видите вы, ваш руководитель и HR.','open':'documents'}
            if any(x in q for x in ('время','смен','работал','работала','час','таймер')):
                shift=c.execute('SELECT * FROM work_shifts WHERE user_id=? ORDER BY id DESC LIMIT 1',(u['id'],)).fetchone()
                if shift:
                    return {**base,'answer':f'Последняя смена началась {shift["started_at"][:16].replace("T"," ")}. Учтённое рабочее время: {int(shift["work_seconds"]//3600):02}:{int(shift["work_seconds"]%3600//60):02}. Историю можно открыть в профиле.','open':'profile'}
                return {**base,'answer':'Записей о сменах пока нет. Нажмите «Начать работу», а в конце — «Завершить день».','open':'office'}
            if any(x in q for x in ('коллег','сотрудник','кто поможет','найти человека','сообщени','чат')):
                return {**base,'answer':'В «Коллегах» можно найти сотрудника по роли и открыть рабочую карточку. В «Сообщениях» можно начать внутренний чат. Также можно написать мне: «Напиши Санжару: текст сообщения».','open':'directory'}
            if any(x in q for x in ('профил','должност','руководител','отдел','подраздел')):
                return {**base,'answer':f'Вы — {u["name"]}, {u["position"]}, подразделение «{u["department"]}». Руководитель: {me["manager_name"]}. Официальные поля доступны только для чтения.','open':'profile'}
            # Broader word-overlap and fuzzy retrieval over every allowed article.
            words=set(re.findall(r'[а-яёa-z]{3,}',q))
            candidates=[]
            for a in rows(c,'SELECT * FROM knowledge'):
                if u['role'] not in a['roles'].split(','): continue
                corpus=(a['title']+' '+a['section']+' '+a['keywords']+' '+a['body']).lower()
                overlap=sum(2 if w in a['keywords'] else 1 for w in words if w in corpus)
                ratio=difflib.SequenceMatcher(None,q,(a['title']+' '+a['keywords']).lower()).ratio()
                candidates.append((overlap+ratio,a))
            best=max(candidates,key=lambda x:x[0]) if candidates else (0,None)
            if best[1] and best[0]>=1.25:
                a=best[1]
                return {**base,'answer':a['body'],'sources':[{'id':a['id'],'title':a['title']+' · '+a['section']}],'kind':'knowledge'}
            return {**base,'answer':'Я поняла вопрос, но в проверенных материалах нет точного правила. Могу помочь найти сотрудника, открыть нужный раздел или подготовить сообщение HR. Уточните, что именно хотите сделать.','kind':'clarify'}
        raise APIError(404,'Не найдено')

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,default=int(os.environ.get('PORT','8765'))); parser.add_argument('--host',default='127.0.0.1'); args=parser.parse_args()
    init_db()
    server=ThreadingHTTPServer((args.host,args.port),Handler)
    print(f'JanaMen готов: http://{args.host}:{args.port}',flush=True)
    server.serve_forever()
