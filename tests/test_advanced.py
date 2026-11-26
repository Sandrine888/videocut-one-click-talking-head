import json
from dataclasses import replace
from pathlib import Path

import pytest

from videocut import advanced, pipeline
from videocut.transcribe import TranscriptResult, CharTimestamp
from tests.test_generate_media import real_video


def speech(path):
    return TranscriptResult(str(path), '周三周四', 3.0, [CharTimestamp(c, s, e) for c, s, e in
        zip('周三周四', (.4, .8, 1.6, 2.0), (.8, 1.2, 2.0, 2.4))])


def response():
    return [{'id':1, 'quote':'周三', 'kind':'重说', 'reason':'随后更正为周四'},
            {'id':2, 'quote':'不存在', 'kind':'冗余', 'reason':'不应采纳'}]


def test_review_and_selected_cut_share_real_video_and_subtitle_clock(real_video, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline,'transcribe_with_cache',lambda path, **kw: speech(path))
    monkeypatch.setattr(advanced,'configured_client', lambda: object())
    monkeypatch.setattr(advanced,'ask',lambda *a:json.dumps(response()))
    opts=pipeline.GenerateOptions(str(real_video),str(tmp_path/'out'),mode='advanced')
    review=pipeline.generate(opts)
    assert review['deletions']==[] and [r['text'] for r in review['suggestions']]==['周三']
    automatic=pipeline.generate(replace(opts,auto_apply=True))
    monkeypatch.setattr(advanced,'ask',lambda *a:pytest.fail('已审核的建议不应再次调用模型'))
    selected=pipeline.generate(replace(opts,review_task=review['task_id'],selected_ids=(1,)))
    for result in (automatic, selected):
        assert result['applied_ids']==[1] and abs(result['output_media']['duration']-2.2)<.051
        subs=json.loads(Path(result['subtitles']).read_text('utf-8'))
        assert subs[0]['text']=='周四' and subs[0]['start']==.8
        assert '00:00:00,800' in Path(result['srt']).read_text('utf-8')
    with pytest.raises(pipeline.GenerationError,match='有效的建议'):
        pipeline.generate(replace(opts,review_task=review['task_id'],selected_ids=(23,)))


def test_ambiguous_substrings_need_occurrence_and_all_speech_is_protected(monkeypatch):
    monkeypatch.setattr(advanced,'configured_client',lambda:object())
    transcript=TranscriptResult('x','周三周三',2,[CharTimestamp(c,i*.2,(i+1)*.2) for i,c in enumerate('周三周三')])
    row=response()[0]
    monkeypatch.setattr(advanced,'ask',lambda *a:json.dumps([row]))
    assert advanced.analyze(transcript)==[]
    row['occurrence']=2
    assert advanced.analyze(transcript)[0]['start']==.4
    row.update(quote='周三周三',occurrence=1)
    with pytest.raises(ValueError,match='全部发言'):
        advanced.analyze(transcript)


def test_compatible_service_and_fallback_reuse_cached_speech(real_video, tmp_path, monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    from videocut import transcribe

    prompts = []
    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            prompts.append(data['messages'][0]['content'])
            status = 429 if len(prompts) == 2 else 200
            reply = {'choices':[{'index':0,'message':{'role':'assistant','content':'OK'}}]} if status == 200 else {'error':{'message':'Quota'}}
            body = json.dumps(reply).encode()
            self.send_response(status)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Content-Type','application/json')
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1',0), Provider)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    config_file = tmp_path/'advanced.json'
    monkeypatch.setattr(advanced,'settings_path',lambda:config_file)
    model = tmp_path/'model'
    model.mkdir()
    for name in ('config.yaml','model.pt'):
        (model/name).touch()
    called = []
    def recognize(path, **kwargs):
        called.append(path)
        return speech(path)
    monkeypatch.setattr(transcribe,'transcribe_video',recognize)
    opts = pipeline.GenerateOptions(str(real_video), str(tmp_path/'out'), model_name=str(model), mode='advanced')
    try:
        settings = advanced.configure(dict(provider='compatible',key='offline-test-only',model='fixture',
            base_url=f'http://127.0.0.1:{server.server_port}/v1'))
        assert settings['configured'] and 'offline-test-only' not in config_file.read_text('utf-8')
        with pytest.raises(pipeline.GenerationError, match='额度'):
            pipeline.generate(opts)
        result = pipeline.generate(replace(opts,mode='quick'))
        assert result['cache_hit'] and len(called)==1 and len(prompts)==2
        sent=json.loads(prompts[1].split('\n')[-1]); assert sent==[{'id':1,'text':'周三周四'}]
    finally:
        server.shutdown()
        server.server_close()
