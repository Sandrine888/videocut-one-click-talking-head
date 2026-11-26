"""Noninteractive command adapter; no License or optional AI-service setup."""

import json
from ..pipeline import GenerateOptions, generate, load_adapters


def run_generate(video, output_dir="results", trim_silence=False, template=None,
                 adapters=None, model_name="paraformer-zh", mode="quick", auto_apply=False):
    def progress(event):
        print(f"[{event['stage']}] {event['message']}", flush=True)
    options = GenerateOptions(video=video, output_dir=output_dir,
                              trim_silence=trim_silence, template=template, model_name=model_name,
                              mode=mode, auto_apply=auto_apply)
    result = generate(options, adapters=load_adapters(adapters), on_event=progress)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result
