# https://talonvoice.slack.com/archives/G9YTMSZ2T/p1633126802119900
from talon import speech_system
def print_timings(j):
    phrase = None
    if "phrase" in j:
        if "parsed" in j:
            phrase = getattr(j["parsed"], "_unmapped", j["phrase"])
        else:
            phrase = j["phrase"]

        phrase = " ".join(word.split("\\")[0] for word in phrase)

    print(f"'{phrase}'")

    if '_metadata' in j:
        meta = j['_metadata']
        status  = f"[audio]={meta['audio_ms']:.3f}ms "
        status += f"[compile]={meta['compile_ms']:.3f}ms "
        status += f"[emit]={meta['emit_ms']:.3f}ms "
        status += f"[decode]={meta['decode_ms']:.3f}ms "
        status += f"[total]={meta['total_ms']:.3f}ms "
        print(status)
    else:
        print(f'print_timings: {j=}')
speech_system.register('phrase', print_timings)
