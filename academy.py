"""Role learning tracks, private material collections and HR assignments."""
import base64
import binascii
import json
import re
from pathlib import Path


def track(person):
    if person['role']=='hr': return 'hr'
    if person['role']=='manager': return 'manager'
    if person['department']=='Склад': return 'warehouse'
    if person['id'] in (6,7): return 'operations'
    return 'client'


def award(c,uid,cid,kind,now):
    c.execute('INSERT OR IGNORE INTO learning_steps VALUES(?,?,?,?,?)',(uid,cid,kind,100,now()))


def starter_assignments(c,specs,now):
    for cid in [1,2]+[s['id'] for s in specs]:
        course=c.execute('SELECT * FROM courses WHERE id=?',(cid,)).fetchone()
        if not course or c.execute("SELECT 1 FROM academy_assignments WHERE course_id=? AND target_type='program'",(cid,)).fetchone():continue
        recipients=c.execute('SELECT user_id FROM enrollments WHERE course_id=?',(cid,)).fetchall()
        if not recipients:continue
        aid=c.execute("INSERT INTO academy_assignments(title,description,kind,course_id,created_by,target_type,target_value,created_at) VALUES(?,?,'course',?,3,'program','По должности',?)",(course['title'],'Стартовая программа обучения',cid,now())).lastrowid
        for p in recipients:c.execute('INSERT INTO academy_recipients VALUES(?,?,NULL)',(aid,p['user_id']))
    if not c.execute("SELECT 1 FROM app_migrations WHERE name='academy_personal_examples_v1'").fetchone():
        samples=[(1,'Разбор сложного обращения','Памятка для общения с клиентом','1. Выслушайте запрос и уточните номер отправления.\n2. Проверьте историю и отделите факт от предположения.\n3. Предложите доступный следующий шаг.\n4. Запишите договорённость и срок ответа.\n5. Убедитесь, что вопрос решён.'),(4,'Передача смены на складе','Чек-лист для подготовки передачи','1. Сверьте фактические отправления с учётом.\n2. Отделите единицы с расхождениями.\n3. Запишите идентификаторы и проверенные факты.\n4. Передайте открытые вопросы ответственному.\n5. Подтвердите получение смены.'),(5,'Проверка обращения перед передачей','Персональная памятка для Армана','Перед передачей обращения проверьте:\n• номер и актуальный статус;\n• что именно просит клиент;\n• какие проверки уже выполнены;\n• кто отвечает за следующий шаг;\n• когда ожидается обратная связь.\nНе включайте лишние персональные данные.')]
        for uid,title,description,body in samples:
            aid=c.execute("INSERT INTO academy_assignments(title,description,kind,created_by,target_type,target_value,created_at) VALUES(?,?,'folder',3,'employee',?,?)",(title,description,str(uid),now())).lastrowid
            c.execute('INSERT INTO academy_recipients VALUES(?,?,NULL)',(aid,uid))
            data=body.encode('utf-8');c.execute('INSERT INTO academy_files(assignment_id,filename,mime,size,content) VALUES(?,?,?,?,?)',(aid,'instruction.txt','text/plain; charset=utf-8',len(data),data))
            c.execute('INSERT INTO notifications(user_id,title,body,kind,target_id,created_at) VALUES(?,?,?,?,?,?)',(uid,'Новые учебные материалы',title,'academy_material',aid,now()))
        c.execute("INSERT INTO app_migrations VALUES('academy_personal_examples_v1')")


def initialize(c,now):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS learning_steps(user_id INTEGER REFERENCES users(id),course_id INTEGER REFERENCES courses(id),kind TEXT,xp INTEGER,created_at TEXT,PRIMARY KEY(user_id,course_id,kind));
    CREATE TABLE IF NOT EXISTS academy_assignments(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,description TEXT NOT NULL,kind TEXT NOT NULL,course_id INTEGER REFERENCES courses(id),created_by INTEGER REFERENCES users(id),target_type TEXT,target_value TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS academy_recipients(assignment_id INTEGER REFERENCES academy_assignments(id),user_id INTEGER REFERENCES users(id),read_at TEXT,PRIMARY KEY(assignment_id,user_id));
    CREATE TABLE IF NOT EXISTS academy_files(id INTEGER PRIMARY KEY AUTOINCREMENT,assignment_id INTEGER REFERENCES academy_assignments(id),filename TEXT,mime TEXT,size INTEGER,content BLOB);
    CREATE TABLE IF NOT EXISTS course_tracks(course_id INTEGER PRIMARY KEY REFERENCES courses(id),tracks TEXT);
    ''')
    source=Path(__file__).parent/'content'/'academy.json'
    specs=json.loads(source.read_text()) if source.exists() else []
    c.execute('UPDATE knowledge SET body=? WHERE id=2',('Jana Academy показывает программу по вашей должности и персональные материалы от HR. Просмотр не менее 90% видео даёт один уровень, тест от 70% — ещё один. Текстовый курс даёт один уровень после теста. Всего десять уровней; повторные награды за тот же материал не начисляются. Если тест не пройден, материал нужно изучить заново. HR назначает курсы и папки сотруднику, должности или подразделению в разделе управления внутри Academy.',))
    c.execute('UPDATE knowledge SET body=? WHERE id=4',('В центре уведомлений появляются изменения статусов заявок, сообщения и новые назначения обучения. Нажмите на событие, чтобы открыть заявку, диалог, курс или личную папку материалов. Завершение обучения и изменение уровня не отправляют уведомления руководителю и HR.',))
    for spec in specs:
        if not c.execute('SELECT 1 FROM courses WHERE id=?',(spec['id'],)).fetchone(): continue
        fresh=not c.execute('SELECT 1 FROM course_tracks WHERE course_id=?',(spec['id'],)).fetchone()
        c.execute('INSERT OR REPLACE INTO course_tracks VALUES(?,?)',(spec['id'],json.dumps(spec.get('tracks',['client','warehouse','operations','manager','hr']))))
        if fresh:
            for p in c.execute('SELECT * FROM users').fetchall():
                if track(p) in spec.get('tracks',[]):
                    added=c.execute('INSERT OR IGNORE INTO enrollments(user_id,course_id,assigned_by,assigned_at) VALUES(?,?,3,?)',(p['id'],spec['id'],now()))
                    if added.rowcount:c.execute('INSERT INTO notifications(user_id,title,body,kind,target_id,created_at) VALUES(?,?,?,?,?,?)',(p['id'],'Новое обучение',spec['title'],'course',spec['id'],now()))
    migration='academy_tracks_levels_v3'
    if c.execute('SELECT 1 FROM app_migrations WHERE name=?',(migration,)).fetchone():
        starter_assignments(c,specs,now)
        return
    for p in c.execute('SELECT * FROM users').fetchall():
        for course in c.execute('SELECT id FROM courses').fetchall():
            spec=next((s for s in specs if s['id']==course['id']),None)
            suitable=spec is None or track(p) in spec.get('tracks',[])
            if suitable:
                c.execute('INSERT OR IGNORE INTO enrollments(user_id,course_id,assigned_by,assigned_at) VALUES(?,?,3,?)',(p['id'],course['id'],now()))
            elif not c.execute('SELECT 1 FROM xp_awards WHERE user_id=? AND course_id=?',(p['id'],course['id'])).fetchone():
                c.execute('DELETE FROM video_progress WHERE user_id=? AND course_id=?',(p['id'],course['id']))
                c.execute('DELETE FROM enrollments WHERE user_id=? AND course_id=?',(p['id'],course['id']))
                c.execute("DELETE FROM notifications WHERE user_id=? AND kind='course' AND target_id=?",(p['id'],course['id']))
    for old in c.execute('SELECT * FROM xp_awards').fetchall():
        lessons=json.loads(c.execute('SELECT lessons FROM courses WHERE id=?',(old['course_id'],)).fetchone()[0])
        if lessons[0].get('video'):award(c,old['user_id'],old['course_id'],'watch',now)
        award(c,old['user_id'],old['course_id'],'test',now)
    c.execute('INSERT INTO app_migrations VALUES(?)',(migration,))
    starter_assignments(c,specs,now)


def file_data(item,require):
    require(isinstance(item,dict),400,'Некорректное описание файла')
    filename=str(item.get('filename','')).strip()
    allowed={'.pdf':'application/pdf','.txt':'text/plain; charset=utf-8','.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','.pptx':'application/vnd.openxmlformats-officedocument.presentationml.presentation','.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','.mp4':'video/mp4','.webm':'video/webm','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg'}
    suffix=Path(filename).suffix.lower()
    require(0<len(filename)<=180 and '/' not in filename and '\\' not in filename and suffix in allowed,400,'Поддерживаются PDF, DOCX, PPTX, XLSX, TXT, MP4, WebM и изображения')
    try: data=base64.b64decode(item.get('content',''),validate=True)
    except (binascii.Error,ValueError):require(False,400,'Не удалось прочитать файл')
    require(0<len(data)<=50*1024*1024,413,'Файл должен быть не больше 50 МБ')
    valid={'.pdf':data.startswith(b'%PDF-'),'.docx':data.startswith(b'PK'),'.pptx':data.startswith(b'PK'),'.xlsx':data.startswith(b'PK'),'.mp4':data[4:8]==b'ftyp','.webm':data.startswith(bytes.fromhex('1a45dfa3')),'.png':data.startswith(b'\x89PNG'),'.jpg':data.startswith(b'\xff\xd8'),'.jpeg':data.startswith(b'\xff\xd8')}
    if suffix=='.txt':
        try:data.decode('utf-8')
        except UnicodeError:require(False,400,'Текстовый файл должен быть в UTF-8')
    else:require(valid.get(suffix,False),400,'Содержимое файла не соответствует расширению')
    return filename,allowed[suffix],data


def route(c,u,method,path,b,require,notify,now,BinaryDownload,course_data):
    hr=u['role']=='hr'
    if path=='/api/academy/options' and method=='GET':
        require(hr)
        people=[dict(p) for p in c.execute('SELECT id,name,position,department FROM users ORDER BY name')]
        catalog=[dict(p) for p in c.execute('SELECT id,title,duration FROM courses ORDER BY id')]
        return {'people':people,'positions':sorted({p['position'] for p in people}),'departments':sorted({p['department'] for p in people}),'courses':catalog}
    if path=='/api/academy/assignments' and method=='GET':
        assignments=c.execute('SELECT a.*,u.name as author FROM academy_assignments a JOIN users u ON u.id=a.created_by '+('' if hr else 'JOIN academy_recipients r ON r.assignment_id=a.id AND r.user_id=? ')+'ORDER BY a.id DESC',() if hr else (u['id'],)).fetchall()
        result=[]
        for row in assignments:
            item=dict(row)
            recipients=[dict(p) for p in c.execute('SELECT u.id,u.name,u.position,r.read_at,e.completed_at,e.score FROM academy_recipients r JOIN users u ON u.id=r.user_id LEFT JOIN enrollments e ON e.user_id=u.id AND e.course_id=? WHERE r.assignment_id=?',(item['course_id'],item['id']))]
            item['recipients']=recipients if hr else [p for p in recipients if p['id']==u['id']]
            item['files']=[dict(f) for f in c.execute('SELECT id,filename,mime,size FROM academy_files WHERE assignment_id=?',(item['id'],))]
            result.append(item)
        return result
    if path=='/api/academy/assignments' and method=='POST':
        require(hr)
        title=str(b.get('title','')).strip();description=str(b.get('description','')).strip()
        require(1<=len(title)<=160 and len(description)<=3000,400,'Укажите название до 160 символов и описание до 3000')
        target=b.get('target_type');value=str(b.get('target_value','')).strip()
        require(target in ('employee','position','department'),400,'Выберите сотрудника, должность или подразделение')
        field={'employee':'id','position':'position','department':'department'}[target]
        people=c.execute('SELECT id FROM users WHERE '+field+'=?',(value,)).fetchall()
        require(bool(people),400,'Не найдены получатели')
        kind=b.get('kind');require(kind in ('course','folder','new_course'),400,'Выберите курс или папку материалов')
        files=b.get('files',[]);require(isinstance(files,list) and len(files)<=6,400,'В папке может быть до 6 файлов')
        decoded=[file_data(f,require) for f in files]
        require(sum(len(f[2]) for f in decoded)<=50*1024*1024,413,'Общий размер материалов — не больше 50 МБ')
        cid=None
        c.execute('BEGIN IMMEDIATE')
        if kind=='course':
            cid=int(b.get('course_id',0));require(c.execute('SELECT 1 FROM courses WHERE id=?',(cid,)).fetchone(),404,'Курс не найден')
        elif kind=='folder':require(bool(decoded),400,'Добавьте хотя бы один файл или видео')
        else:
            require(len(decoded)==1 and decoded[0][1].startswith('video/'),400,'Для видеокурса загрузите одно видео MP4 или WebM')
            quiz=b.get('quiz');require(isinstance(quiz,list) and len(quiz)==10,400,'Для курса нужны 10 вопросов')
            for q in quiz:
                require(isinstance(q,dict) and 1<=len(str(q.get('question','')).strip())<=300 and isinstance(q.get('options'),list) and 2<=len(q['options'])<=4 and all(isinstance(x,str) and 1<=len(x.strip())<=200 for x in q['options']) and type(q.get('correct')) is int and 0<=q['correct']<len(q['options']),400,'Заполните вопросы, варианты и правильные ответы')
            seconds=float(b.get('duration_seconds',0));require(1<=seconds<=7200,400,'Не удалось определить длительность видео')
            cid=c.execute('SELECT coalesce(max(id),0)+1 FROM courses').fetchone()[0]
            lesson={'title':title,'body':description,'duration_seconds':seconds,'chapters':[],'badge':title,'video':'pending'}
            c.execute('INSERT INTO courses VALUES(?,?,?,?,?,?)',(cid,title,description,f'{int(seconds)//60}:{int(seconds)%60:02d} · видео',json.dumps([lesson],ensure_ascii=False),json.dumps(quiz,ensure_ascii=False)))
        aid=c.execute('INSERT INTO academy_assignments(title,description,kind,course_id,created_by,target_type,target_value,created_at) VALUES(?,?,?,?,?,?,?,?)',(title,description,'course' if cid else 'folder',cid,u['id'],target,value,now())).lastrowid
        for filename,mime,data in decoded:
            fid=c.execute('INSERT INTO academy_files(assignment_id,filename,mime,size,content) VALUES(?,?,?,?,?)',(aid,filename,mime,len(data),data)).lastrowid
            if kind=='new_course':
                lesson['video']=f'/api/academy/files/{fid}'
                c.execute('UPDATE courses SET lessons=? WHERE id=?',(json.dumps([lesson],ensure_ascii=False),cid))
        for person in people:
            uid=person['id'];c.execute('INSERT INTO academy_recipients VALUES(?,?,NULL)',(aid,uid))
            if cid:c.execute('INSERT OR IGNORE INTO enrollments(user_id,course_id,assigned_by,assigned_at) VALUES(?,?,?,?)',(uid,cid,u['id'],now()))
            notify(c,uid,'Новое обучение' if cid else 'Новые учебные материалы',title,'course' if cid else 'academy_material',cid or aid)
        return {'id':aid,'recipients':len(people),'course_id':cid}
    match=re.fullmatch(r'/api/academy/assignments/(\d+)/read',path)
    if match and method=='POST':
        aid=int(match[1]);require(hr or c.execute('SELECT 1 FROM academy_recipients WHERE assignment_id=? AND user_id=?',(aid,u['id'])).fetchone(),403)
        c.execute('UPDATE academy_recipients SET read_at=coalesce(read_at,?) WHERE assignment_id=? AND user_id=?',(now(),aid,u['id']))
        c.execute("UPDATE notifications SET is_read=1 WHERE user_id=? AND kind='academy_material' AND target_id=?",(u['id'],aid))
        return {'ok':True}
    match=re.fullmatch(r'/api/academy/files/(\d+)',path)
    if match and method=='GET':
        f=c.execute('SELECT * FROM academy_files WHERE id=?',(int(match[1]),)).fetchone();require(f is not None,404,'Материал не найден')
        require(hr or c.execute('SELECT 1 FROM academy_recipients WHERE assignment_id=? AND user_id=?',(f['assignment_id'],u['id'])).fetchone() or c.execute('SELECT 1 FROM academy_assignments a JOIN enrollments e ON e.course_id=a.course_id WHERE a.id=? AND e.user_id=?',(f['assignment_id'],u['id'])).fetchone(),403,'Этот материал вам не назначен')
        return BinaryDownload(f['content'],f['mime'],f['filename'])
    require(False,404,'Раздел обучения не найден')
