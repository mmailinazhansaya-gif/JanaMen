"""Employee tasks, private attachments, drafts and submitted results."""
import base64
import binascii
import io
import re
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

TZ = timezone(timedelta(hours=5))
MAX_FILE = 8 * 1024 * 1024


def initialize(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS employee_tasks(
      id INTEGER PRIMARY KEY AUTOINCREMENT, author_id INTEGER NOT NULL REFERENCES users(id),
      assignee_id INTEGER REFERENCES users(id), title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
      deadline REAL, status TEXT NOT NULL CHECK(status IN ('draft','active','completed')),
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL, sent_at TEXT, completed_at TEXT,
      result_text TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS task_files(
      id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL REFERENCES employee_tasks(id),
      kind TEXT NOT NULL CHECK(kind IN ('assignment','result')), filename TEXT NOT NULL,
      mime TEXT NOT NULL, size INTEGER NOT NULL, content BLOB NOT NULL);
    CREATE INDEX IF NOT EXISTS task_assignee ON employee_tasks(assignee_id,status);
    ''')


def can_assign(u, recipient):
    return bool(recipient and recipient['id'] != u['id'] and
                (u['role'] == 'hr' or (u['role'] == 'manager' and recipient['manager_id'] == u['id'])))


def recipients(c, u):
    return [dict(p) for p in c.execute('SELECT id,name,position,department,manager_id FROM users ORDER BY name')
            if can_assign(u, p)]


def fetch_task(c, tid):
    row = c.execute('''SELECT t.*,a.name AS author_name,a.role AS author_role,p.name AS assignee_name,
                       p.manager_id,p.position AS assignee_position FROM employee_tasks t
                       JOIN users a ON a.id=t.author_id LEFT JOIN users p ON p.id=t.assignee_id WHERE t.id=?''', (tid,)).fetchone()
    return dict(row) if row else None


def can_read(u, task):
    if task['status'] == 'draft': return task['author_id'] == u['id']
    return (u['id'] in (task['author_id'], task['assignee_id']) or u['role'] == 'hr' or
            (u['role'] == 'manager' and task['manager_id'] == u['id']))


def view(c, u, task, detail=False):
    result = {k: task[k] for k in ('id','author_id','author_name','author_role','assignee_id','assignee_name',
        'assignee_position','title','description','created_at','updated_at','sent_at','completed_at','version')}
    result['status'] = 'overdue' if task['status'] == 'active' and task['deadline'] < time.time() else task['status']
    result['deadline'] = datetime.fromtimestamp(task['deadline'], TZ).isoformat() if task['deadline'] else None
    result['can_edit'] = task['status'] == 'draft' and task['author_id'] == u['id']
    result['can_submit'] = task['status'] == 'active' and task['assignee_id'] == u['id']
    if detail:
        result['result_text'] = task['result_text']
        result['files'] = [dict(f) for f in c.execute('SELECT id,kind,filename,mime,size FROM task_files WHERE task_id=? ORDER BY id', (task['id'],))]
    return result


def parse_file(value, require):
    require(isinstance(value, dict), 400, 'Выберите файл')
    filename = str(value.get('filename', '')).replace('\\', '/').split('/')[-1]
    require(1 <= len(filename) <= 180 and not any(ord(x) < 32 for x in filename), 400, 'Некорректное имя файла')
    ext = Path(filename).suffix.lower()
    types = {'.pdf':'application/pdf','.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
             '.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
             '.pptx':'application/vnd.openxmlformats-officedocument.presentationml.presentation',
             '.txt':'text/plain; charset=utf-8','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg'}
    require(ext in types, 400, 'Поддерживаются PDF, DOCX, XLSX, PPTX, TXT, PNG и JPG')
    encoded = value.get('content')
    require(isinstance(encoded, str) and len(encoded) <= (MAX_FILE+2)//3*4, 413, 'Файл должен быть не больше 8 МБ')
    try: data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error): require(False, 400, 'Не удалось прочитать файл')
    require(0 < len(data) <= MAX_FILE, 413, 'Файл должен быть от 1 байта до 8 МБ')
    if ext == '.pdf': require(data.startswith(b'%PDF-'), 400, 'Некорректный PDF')
    elif ext == '.png': require(data.startswith(b'\x89PNG\r\n\x1a\n'), 400, 'Некорректный PNG')
    elif ext in ('.jpg','.jpeg'): require(data.startswith(b'\xff\xd8\xff'), 400, 'Некорректный JPG')
    elif ext == '.txt':
        try: data.decode('utf-8')
        except UnicodeDecodeError: require(False, 400, 'Текстовый файл должен быть в UTF-8')
    else:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = archive.namelist()
                prefix = {'.docx':'word/', '.xlsx':'xl/', '.pptx':'ppt/'}[ext]
                require('[Content_Types].xml' in names and any(n.startswith(prefix) for n in names), 400, 'Некорректный офисный файл')
        except (zipfile.BadZipFile, ValueError): require(False, 400, 'Некорректный офисный файл')
    return filename, types[ext], len(data), data


def fields(c, u, body, require, sending):
    title = str(body.get('title', '')).strip()
    description = str(body.get('description', '')).strip()
    require(1 <= len(title) <= 180, 400, 'Укажите наименование задачи, до 180 символов')
    require(len(description) <= 5000, 400, 'Описание — до 5000 символов')
    rid = body.get('assignee_id')
    require(rid is None or type(rid) is int, 400, 'Выберите сотрудника')
    recipient = c.execute('SELECT * FROM users WHERE id=?', (rid,)).fetchone() if rid is not None else None
    if rid is not None: require(can_assign(u, recipient), 403, 'Нельзя назначить задачу этому сотруднику')
    if sending: require(recipient is not None, 400, 'Выберите, кому отправить задачу')
    deadline = None
    if body.get('deadline'):
        try:
            parsed = datetime.fromisoformat(str(body['deadline']).replace('Z','+00:00'))
            require(parsed.tzinfo is not None, 400, 'Укажите часовой пояс дедлайна')
            deadline = parsed.timestamp()
        except (ValueError, OverflowError): require(False, 400, 'Некорректный дедлайн')
    if sending: require(deadline is not None and deadline > time.time(), 400, 'Дедлайн должен быть в будущем')
    file = parse_file(body['file'], require) if body.get('file') is not None else None
    return title, description, rid, deadline, file


def route(c, u, method, path, body, require, notify, now, BinaryDownload):
    if path == '/api/tasks/options' and method == 'GET':
        require(u['role'] in ('manager','hr'))
        return {'recipients': recipients(c,u)}
    if path == '/api/tasks' and method == 'GET':
        tasks = [fetch_task(c,r['id']) for r in c.execute('SELECT id FROM employee_tasks ORDER BY id DESC')]
        return [view(c,u,t) for t in tasks if can_read(u,t)]
    match = re.fullmatch(r'/api/tasks/(\d+)(?:/(submit|files/(\d+)))?', path)
    if match and method == 'GET':
        task = fetch_task(c,int(match[1])); require(task is not None,404,'Задача не найдена')
        require(can_read(u,task))
        if match[3]:
            file = c.execute('SELECT * FROM task_files WHERE id=? AND task_id=?',(int(match[3]),task['id'])).fetchone()
            require(file is not None,404,'Файл не найден')
            return BinaryDownload(file['content'],file['mime'],file['filename'])
        require(match[2] is None,404,'Не найдено')
        return view(c,u,task,True)
    if (path == '/api/tasks' or match and match[2] is None) and method == 'POST':
        require(u['role'] in ('manager','hr'))
        require(body.get('action') in ('draft','send'),400,'Выберите отправку или сохранение черновика')
        sending = body['action'] == 'send'
        c.execute('BEGIN IMMEDIATE')
        old = None
        if match:
            old = fetch_task(c,int(match[1])); require(old is not None,404,'Задача не найдена')
            require(old['author_id'] == u['id'])
            require(old['status'] == 'draft',409,'Отправленную задачу нельзя менять как черновик')
            require(type(body.get('version')) is int and body['version'] == old['version'],409,'Черновик изменён. Откройте его заново')
        title, description, rid, deadline, file = fields(c,u,body,require,sending)
        stamp=now();status='active' if sending else 'draft'
        if old:
            tid=old['id']
            c.execute('UPDATE employee_tasks SET title=?,description=?,assignee_id=?,deadline=?,status=?,updated_at=?,sent_at=?,version=version+1 WHERE id=?',
                      (title,description,rid,deadline,status,stamp,stamp if sending else None,tid))
        else:
            tid=c.execute('INSERT INTO employee_tasks(author_id,assignee_id,title,description,deadline,status,created_at,updated_at,sent_at) VALUES(?,?,?,?,?,?,?,?,?)',
                          (u['id'],rid,title,description,deadline,status,stamp,stamp,stamp if sending else None)).lastrowid
        if file or body.get('remove_file') is True: c.execute("DELETE FROM task_files WHERE task_id=? AND kind='assignment'",(tid,))
        if file: c.execute("INSERT INTO task_files(task_id,kind,filename,mime,size,content) VALUES(?,'assignment',?,?,?,?)",(tid,*file))
        if sending: notify(c,rid,'Новая задача',u['name']+' · '+title,'task',tid)
        return view(c,u,fetch_task(c,tid),True)
    if match and match[2] == 'submit' and method == 'POST':
        c.execute('BEGIN IMMEDIATE')
        task=fetch_task(c,int(match[1]));require(task is not None,404,'Задача не найдена')
        require(task['assignee_id']==u['id'])
        require(task['status']=='active',409,'Задача уже завершена или ещё не отправлена')
        result=str(body.get('result_text','')).strip()
        require(len(result)<=5000,400,'Результат — до 5000 символов')
        file=parse_file(body['file'],require) if body.get('file') is not None else None
        require(result or file,400,'Опишите результат или приложите файл')
        stamp=now()
        c.execute("UPDATE employee_tasks SET status='completed',result_text=?,completed_at=?,updated_at=?,version=version+1 WHERE id=?",(result,stamp,stamp,task['id']))
        if file:c.execute("INSERT INTO task_files(task_id,kind,filename,mime,size,content) VALUES(?,'result',?,?,?,?)",(task['id'],*file))
        notify(c,task['author_id'],'Задача выполнена',u['name']+' · '+task['title'],'task',task['id'])
        return view(c,u,fetch_task(c,task['id']),True)
    require(False,404,'Не найдено')


def seed(c, now):
    marker='employee_tasks_demo_v1'
    if c.execute('SELECT 1 FROM app_migrations WHERE name=?',(marker,)).fetchone(): return
    stamp=now();base=datetime.now(TZ)
    examples=[('Разобрать обращения клиентов','Проверьте открытые обращения, уточните сроки ответа и подготовьте краткую сводку.'),
              ('Обновить рабочую инструкцию','Опишите порядок действий на смене и добавьте ответы на три частых вопроса.'),
              ('Подготовить отчёт по смене','Соберите итоги работы, отметьте сложные ситуации и предложите одно улучшение.')]
    for person in c.execute("SELECT * FROM users WHERE role='employee'").fetchall():
        author=person['manager_id'] or 3
        for group in ('active','completed','overdue'):
            for i,(title,description) in enumerate(examples):
                due=(base+timedelta(days=(i+2 if group=='active' else -i-2))).timestamp()
                status='completed' if group=='completed' else 'active'
                created=(base-timedelta(days=8+i)).isoformat()
                finished=datetime.fromtimestamp(due-3600,TZ).isoformat() if status=='completed' else None
                result='Работа выполнена: материалы проверены, результаты собраны и переданы.' if status=='completed' else ''
                tid=c.execute('INSERT INTO employee_tasks(author_id,assignee_id,title,description,deadline,status,created_at,updated_at,sent_at,completed_at,result_text) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                              (author,person['id'],title+' · '+person['department'],description,due,status,created,finished or created,created,finished,result)).lastrowid
                if i==0:
                    data=('Рабочая памятка\n'+description+'\nВымышленный пример для демонстрации JanaMen.').encode()
                    c.execute("INSERT INTO task_files(task_id,kind,filename,mime,size,content) VALUES(?,'assignment',?,'text/plain; charset=utf-8',?,?)",(tid,'instruction.txt',len(data),data))
    for author in c.execute("SELECT * FROM users WHERE role IN ('hr','manager')").fetchall():
        allowed=recipients(c,author)
        if not allowed:continue
        for i,(title,description) in enumerate(examples):
            c.execute('INSERT INTO employee_tasks(author_id,assignee_id,title,description,deadline,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                      (author['id'],allowed[i%len(allowed)]['id'],title,description,(base+timedelta(days=5+i)).timestamp(),'draft',stamp,stamp))
    c.execute('INSERT INTO app_migrations VALUES(?)',(marker,))
