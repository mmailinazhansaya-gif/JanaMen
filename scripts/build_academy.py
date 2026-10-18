"""Build original narrated whiteboard lessons. Requires Pillow, edge-tts, imageio-ffmpeg.
Run from project directory: PYTHONPATH=<media dependencies> python scripts/build_academy.py.
Only the original text in content/academy.json is sent to speech synthesis.
"""
import asyncio,json,subprocess,re,math,shutil,os
from functools import lru_cache
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
import edge_tts,imageio_ffmpeg
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT.parent.parent/'work'/'academy-build';WORK.mkdir(parents=True,exist_ok=True)
ASSETS=ROOT/'static'/'assets';FF=imageio_ffmpeg.get_ffmpeg_exe()
FONT='/System/Library/Fonts/Supplemental/Arial.ttf'
if not Path(FONT).exists(): FONT='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
@lru_cache(maxsize=16)
def font(n):return ImageFont.truetype(FONT,n)
def run(args):return subprocess.run([FF,'-hide_banner','-y',*args],capture_output=True,check=True)
def duration(p):
 r=subprocess.run([FF,'-i',str(p)],capture_output=True,text=True)
 m=re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)',r.stderr)
 return int(m[1])*3600+int(m[2])*60+float(m[3])
def wrap(text,f,width):
 lines=[];line=''
 for word in text.split():
  candidate=(line+' '+word).strip()
  if f.getlength(candidate)>width and line:lines.append(line);line=word
  else:line=candidate
 return lines+[line]
def board(c,i,progress):
 s=c['scenes'][i];im=Image.new('RGB',(1280,720),'#f8f6ed');d=ImageDraw.Draw(im)
 for y in range(96,690,32):d.line((40,y,1240,y),fill='#e6e8dd',width=1)
 d.rectangle((0,0,1280,68),fill='#294d3d');d.text((38,20),'JANA ACADEMY  /  УЧЕБНАЯ ДОСКА',font=font(21),fill='#e5efdc')
 d.text((1120,20),f'{i+1:02d} / 10',font=font(21),fill='#d0dbb5')
 lines=wrap(s['title'],font(40),1150)
 for j,line in enumerate(lines):d.text((54,104+j*46),line,font=font(40),fill='#284d3b')
 d.line((54,203,54+int(1110*min(1,progress*5)),203),fill='#78a46c',width=5)
 for j,point in enumerate(s['points']):
  reveal=max(0,min(1,(progress-(.10+j*.23))/.18));shown=point[:int(len(point)*reveal)]
  if reveal<=0:continue
  y=245+j*114
  d.rounded_rectangle((54,y,108,y+54),radius=10,fill='#dbe8cf');d.text((70,y+8),str(j+1),font=font(29),fill='#416c43')
  ls=wrap(shown,font(32),1030)
  for k,line in enumerate(ls):d.text((132,y+5+k*36),line,font=font(32),fill='#344b41')
  if reveal<1 and ls:
   x=132+font(32).getlength(ls[-1]);yy=y+15+(len(ls)-1)*36
   d.line((x+8,yy+20,x+28,yy-10),fill='#bd7950',width=8)
 d.rectangle((0,682,1280,720),fill='#ebeee2')
 d.text((36,693),'Демонстрационный курс • самостоятельный материал',font=font(15),fill='#6b7c66')
 d.rectangle((0,678,int(1280*(i+progress)/10),682),fill='#789d5e')
 return im
async def speech(c,i,sem):
 p=WORK/c['slug']/f'{i:02}.mp3';p.parent.mkdir(parents=True,exist_ok=True)
 if not p.exists() or not p.stat().st_size:
  async with sem:
   if os.environ.get('ACADEMY_LOCAL_VOICE'):
    text=p.with_suffix('.txt');text.write_text(c['scenes'][i]['narration'])
    audio=p.with_suffix('.aiff')
    await asyncio.to_thread(subprocess.run,['say','-v','Milena','-r','165','-f',str(text),'-o',str(audio)],check=True,capture_output=True)
    await asyncio.to_thread(run,['-i',str(audio),'-af','asetrate=22050*0.84,aresample=24000,atempo=1.190476','-c:a','libmp3lame','-b:a','96k',str(p)])
    print('Narration local',c['slug'],i+1,flush=True)
    return p
   for attempt in range(3):
    try:
     await edge_tts.Communicate(c['scenes'][i]['narration'],'ru-RU-DmitryNeural',rate='+0%').save(str(p));break
    except Exception:
     if attempt==2:raise
     await asyncio.sleep(2)
 print('Narration',c['slug'],i+1,flush=True)
 return p
def stamp(t):
 ms=round(t*1000);return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02}.{ms%1000:03}'
def build(c):
 folder=WORK/c['slug'];raw=[duration(folder/f'{i:02}.mp3') for i in range(10)];total=sum(raw)
 # Keep natural narration within requested 5–6 minutes, with small inter-section pauses.
 target=max(310,min(345,total+10));tempo=total/(target-10)
 durations=[]
 for i in range(10):
  out=folder/f'{i:02}.wav'
  run(['-i',str(folder/f'{i:02}.mp3'),'-af',f'atempo={tempo:.6f},apad=pad_dur=1','-ar','24000','-ac','1',str(out)])
  durations.append(duration(out))
 audiofile=folder/'audio-list.txt';audiofile.write_text('\n'.join(f"file '{folder/f'{i:02}.wav'}'" for i in range(10)))
 run(['-f','concat','-safe','0','-i',str(audiofile),'-c:a','pcm_s16le',str(folder/'narration.wav')])
 images=[];vtt=['WEBVTT',''];elapsed=0
 for i,seconds in enumerate(durations):
  steps=24
  for k in range(steps):
   p=folder/f'board-{i:02}-{k:02}.png';board(c,i,k/(steps-1)).save(p)
   images.extend([f"file '{p}'",f'duration {seconds/steps:.6f}'])
  if i==0:board(c,0,1).save(ASSETS/(c['slug']+'-poster.png'))
  sentences=re.split(r'(?<=[.!?])\s+',c['scenes'][i]['narration']);weight=sum(len(t) for t in sentences)
  t=elapsed
  for sentence in sentences:
   end=t+(seconds-1)*len(sentence)/weight
   vtt.extend([f'{stamp(t)} --> {stamp(end)}',sentence,'']);t=end
  c['scenes'][i]['start']=round(elapsed,2);elapsed+=seconds
 images.append(images[-2]);(folder/'images.txt').write_text('\n'.join(images))
 out=ASSETS/(c['slug']+'.mp4');temporary=folder/'finished.mp4'
 run(['-f','concat','-safe','0','-i',str(folder/'images.txt'),'-i',str(folder/'narration.wav'),'-vf','fps=6','-c:v','libx264','-threads','2','-preset','veryfast','-crf','24','-pix_fmt','yuv420p','-c:a','aac','-b:a','96k','-movflags','+faststart','-shortest',str(temporary)])
 assert 300<=duration(temporary)<=360,'Incomplete lesson video'
 temporary.replace(out)
 (ASSETS/(c['slug']+'.vtt')).write_text('\n'.join(vtt))
 c['duration_seconds']=round(duration(out),2);c['voice']='local-ru-synthetic' if os.environ.get('ACADEMY_LOCAL_VOICE') else 'ru-RU-DmitryNeural';c['video']='/assets/'+out.name
 print('BUILT',out,c['duration_seconds'],flush=True)
async def main():
 courses=json.loads((ROOT/'content/academy.json').read_text());sem=asyncio.Semaphore(4)
 pending=[c for c in courses if not c.get('video') or not (ASSETS/Path(c['video']).name).exists()]
 await asyncio.gather(*(speech(c,i,sem) for c in pending for i in range(10)))
 render_sem=asyncio.Semaphore(2)
 async def render_one(c):
  async with render_sem:
   await asyncio.to_thread(build,c)
   (ROOT/'content/academy.json').write_text(json.dumps(courses,ensure_ascii=False,indent=2))
 await asyncio.gather(*(render_one(c) for c in pending))
if __name__=='__main__':asyncio.run(main())
