"""Build the edit from the owner's real, local recording and measured word timestamps.

Run transcribe_local.py first, then this script, then:
python docs/video/assemble.py --beats docs/video/beats_owner.json --out data/video/demo_with_agmon.mp4
All speech remains at natural speed. Source ranges and subtitle times stay inspectable.
"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
MEDIA = HERE.parents[1] / 'data/video'


def prepare_audio() -> None:
    """Make editable stems from existing local media; no network or generated voice."""
    ffmpeg = shutil.which('ffmpeg')
    if not (MEDIA/'owner_voice.wav').exists():
        subprocess.run([ffmpeg,'-v','error','-i',str(MEDIA/'owner_raw.mp4'),'-vn','-af',
                        'highpass=f=70,loudnorm=I=-16:TP=-1.5:LRA=11','-ar','48000','-ac','2',
                        '-c:a','pcm_s16le',str(MEDIA/'owner_voice.wav')],check=True)
    if not (MEDIA/'demo_music.wav').exists():
        sound = HERE.parents[1]/'data/cache/sound'
        subprocess.run([ffmpeg,'-v','error','-i',str(sound/'score_03fb5bc6b4441c6e.wav'),
                        '-i',str(sound/'score_198eb021cfd47868.wav'),'-filter_complex',
                        '[0:a]aresample=48000,aformat=channel_layouts=stereo[a];'
                        '[1:a]aresample=48000,aformat=channel_layouts=stereo[b];'
                        '[a][b]acrossfade=d=1:c1=tri:c2=tri[out]',
                        '-map','[out]','-c:a','pcm_s16le',str(MEDIA/'demo_music.wav')],check=True)


def clean_words(words: list[dict]) -> list[dict]:
    """Correct recognizer spellings of model names; retain the original ASR separately."""
    out = []
    i = 0
    while i < len(words):
        w = dict(words[i])
        word = w['word'].strip()
        if word == 'Metamodels':
            w['word'] = 'Meta models'
        elif word == 'with' and i+1 < len(words) and words[i+1]['word'].strip() == 'outlabers':
            w.update(word='without labels', end=words[i+1]['end'])
            i += 1
        elif word == 'Bass' and i+1 < len(words) and words[i+1]['word'].strip() == '10.':
            w.update(word='Baseten.', end=words[i+1]['end'])
            i += 1
        elif word.lower() in ('muse', 'muse,'):
            w['word'] = word.capitalize()
        elif word == 'wonder':
            w['word'] = 'Wonder'
        elif word == 'time' and i+1 < len(words) and words[i+1]['word'].strip() == 'edit':
            w['word'] = 'timed'  # confirmed by a second local transcription of the rendered mix
        elif word == 'and' and i > 0 and i+1 < len(words) and words[i-1]['word'].strip() == 'Open' and words[i+1]['word'].strip() == 'Bass':
            w['word'] = 'on'  # ASR spelling in the proper name phrase "Spark Open on Baseten"
        out.append(w)
        i += 1
    return out


def cues(words: list[dict], start: float, end: float, at: float, scene_end: float) -> list[dict]:
    selected = [w for w in words if w['start'] >= start-0.03 and w['end'] <= end+0.03]
    groups, group = [], []
    for w in selected:
        group.append(w)
        if len(group) >= 9 or (len(group) >= 4 and w['word'].rstrip().endswith(('.', ',', '?'))):
            groups.append(group)
            group = []
    if group:
        if groups and len(group) < 4:
            groups[-1].extend(group)
        else:
            groups.append(group)
    result = []
    for i, g in enumerate(groups):
        a = max(0, g[0]['start']-start+at)
        stop = min(scene_end, g[-1]['end']-start+at+0.12)
        if i+1 < len(groups):
            stop = min(stop, groups[i+1][0]['start']-start+at)
        result.append({'start': round(a, 4), 'end': round(stop, 4),
                       'text': ' '.join(w['word'].strip() for w in g).replace('re -cut','re-cut')})
    return result


def stamp(t: float) -> str:
    return f'{int(t)//60}:{t%60:05.2f}'


def main() -> None:
    prepare_audio()
    spec = json.loads((HERE/'beats.json').read_text(encoding='utf-8-sig'))
    spec = copy.deepcopy(spec)
    beats = spec['beats']
    # Rebalance picture holds around the actual takes, without stretching a single spoken word.
    lengths = {1:6.5, 2:10.1, 3:7.5, 6:9.5, 7:8, 8:7.1, 11:8.2, 12:10.5,
               13:12, 15:9.2, 16:6.5, 18:7.9}
    for i, duration in lengths.items():
        beats[i]['dur'] = duration
    beats[2]['in'] = 2
    beats[11]['in'] = 8  # begin on the actual checker scenes, after the page scroll settles
    asr = json.loads((MEDIA/'owner_transcript.json').read_text(encoding='utf-8'))
    words = clean_words([w for s in asr['segments'] for w in s['words']])
    # scene index, source start, selected duration, offset in destination scene
    selections = [(1,0.4,6.5,0), (2,7.03,9.87,0.1), (4,21.35,6.47,0.15),
                  (6,28.55,5.0,0.2), (8,36.68,7.1,0), (9,43.82,5.36,0.2),
                  (11,49.9,8.05,0.05), (15,58.7,8.98,0.1), (18,68.65,7.9,0)]
    for index, start, length, at in selections:
        beat = beats[index]
        if 'camera' in beat:
            del beat['camera']
            beat.update(screen='owner_raw.mp4', **{'in':start})
        beat['speech'] = {'file':'owner_voice.wav', 'in':start, 'duration':length, 'at':at}
        beat['captions'] = cues(words,start,start+length,at,float(beat['dur']))
        for key in ('voiceover','sound'):
            beat.pop(key,None)
        # Explanatory captions resume only in a real pause, never competing with subtitles.
        tail = at + length + 0.15
        if beat.get('caption') and float(beat['dur'])-tail >= 1.2:
            beat['captions'].append({'start':tail,'end':float(beat['dur']),'text':beat['caption']})
    assert round(sum(float(b['dur']) for b in beats)*30)==5400
    spec['music'] = {'file':'demo_music.wav','until':155,'gain':0.16}
    (HERE/'beats_owner.json').write_text(json.dumps(spec,ensure_ascii=False,indent=1)+'\n',encoding='utf-8')
    # Plain subtitle sidecar and a human-readable source-to-sequence edit decision list.
    subtitle, edit = [], ['# Owner recording edit decision list', '',
                         'Whisper ran locally, offline, using the cached small model. No audio was uploaded.', '',
                         '| Sequence | Picture | Recorded speech source |', '|---|---|---|']
    t=0.0
    for beat in beats:
        speech=beat.get('speech')
        src=(f"{speech['in']:.2f}–{speech['in']+speech['duration']:.2f} s" if speech else '—')
        edit.append(f"| {stamp(t)}–{stamp(t+beat['dur'])} | {beat['screen']} | {src} |")
        if speech:
            subtitle += [{'start':t+c['start'],'end':t+c['end'],'text':c['text']}
                         for c in beat['captions'] if c['start']<speech['at']+speech['duration']]
        t+=float(beat['dur'])
    (HERE/'OWNER_EDIT.md').write_text('\n'.join(edit)+'\n',encoding='utf-8')
    def srt_time(seconds: float) -> str:
        ms=round(seconds*1000)
        return f'{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}'
    (MEDIA/'owner_subtitles.srt').write_text('\n\n'.join(
        f"{i+1}\n{srt_time(s['start'])} --> {srt_time(s['end'])}\n{s['text']}"
        for i,s in enumerate(subtitle))+'\n',encoding='utf-8')
    print(f'{t:.1f} s; {sum(s[2] for s in selections):.2f} s actual owner speech; {len(subtitle)} subtitle cues')


if __name__=='__main__':
    main()
