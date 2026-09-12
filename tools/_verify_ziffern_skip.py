#!/usr/bin/env python3
from kern import tts
tts.TTS_BASE = "http://x:8213"
p = tts._ziffern_einzeln("null eins sieben sieben, sechs null null, vier sechs, null null")
print("soll_qwen", repr(tts._ziffern_soll(p)))
print("ziffern_satz", tts.ziffern_satz(
    "Ich wiederhole die Nummer: null eins sieben sieben, sechs null null, vier sechs, null null."))
tts.TTS_BASE = "http://x:8211"
print("soll_cosy", repr(tts._ziffern_soll(p)))
